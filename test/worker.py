#!/usr/bin/env python
#
# Copyright 2013, Google Inc. All rights reserved.
# Use of this source code is governed by a BSD-style license that can
# be found in the LICENSE file.
"""
Tests the robustness and resiliency of vtworkers.
"""

import logging
import unittest
from collections import namedtuple

from vtdb import keyrange_constants

import environment
import utils
import tablet

KEYSPACE_ID_TYPE = keyrange_constants.KIT_UINT64

class ShardTablets(namedtuple('ShardTablets', 'master replicas rdonlys')):
  """ShardTablets is a container for all the tablet.Tablets of a shard.

  `master` should be a single Tablet, while `replicas` and `rdonlys` should be
  lists of Tablets of the appropriate types.
  """

  @property
  def all_tablets(self):
    """Returns a list of all the tablets of the shard.

    Does not guarantee any ordering on the returned tablets.
    """
    return [self.master] + self.replicas + self.rdonlys

  @property
  def replica(self):
    """Returns the first replica Tablet instance for the shard, or None."""
    if self.replicas:
      return self.replicas[0]
    else:
      return None

  @property
  def rdonly(self):
    """Returns the first replica Tablet instance for the shard, or None."""
    if self.rdonlys:
      return self.rdonlys[0]
    else:
      return None

# initial shard, covers everything
shard_master = tablet.Tablet()
shard_replica = tablet.Tablet()
shard_rdonly1 = tablet.Tablet()

# split shards
# range "" - 80
shard_0_master = tablet.Tablet()
shard_0_replica = tablet.Tablet()
shard_0_rdonly1 = tablet.Tablet()
# range 80 - ""
shard_1_master = tablet.Tablet()
shard_1_replica = tablet.Tablet()
shard_1_rdonly1 = tablet.Tablet()

shard_tablets = ShardTablets(shard_master, [shard_replica], [shard_rdonly1])
shard_0_tablets = ShardTablets(shard_0_master, [shard_0_replica], [shard_0_rdonly1])
shard_1_tablets = ShardTablets(shard_1_master, [shard_1_replica], [shard_1_rdonly1])


def setUpModule():
  try:
    environment.topo_server().setup()

    setup_procs = [
        shard_master.init_mysql(),
        shard_replica.init_mysql(),
        shard_rdonly1.init_mysql(),
        shard_0_master.init_mysql(),
        shard_0_replica.init_mysql(),
        shard_0_rdonly1.init_mysql(),
        shard_1_master.init_mysql(),
        shard_1_replica.init_mysql(),
        shard_1_rdonly1.init_mysql(),
        ]
    utils.wait_procs(setup_procs)
  except:
    tearDownModule()
    raise


def tearDownModule():
  if utils.options.skip_teardown:
    return

  teardown_procs = [
      shard_master.teardown_mysql(),
      shard_replica.teardown_mysql(),
      shard_rdonly1.teardown_mysql(),
      shard_0_master.teardown_mysql(),
      shard_0_replica.teardown_mysql(),
      shard_0_rdonly1.teardown_mysql(),
      shard_1_master.teardown_mysql(),
      shard_1_replica.teardown_mysql(),
      shard_1_rdonly1.teardown_mysql(),
      ]
  utils.wait_procs(teardown_procs, raise_on_error=False)

  environment.topo_server().teardown()
  utils.kill_sub_processes()
  utils.remove_tmp_files()

  shard_master.remove_tree()
  shard_replica.remove_tree()
  shard_rdonly1.remove_tree()
  shard_0_master.remove_tree()
  shard_0_replica.remove_tree()
  shard_0_rdonly1.remove_tree()
  shard_1_master.remove_tree()
  shard_1_replica.remove_tree()
  shard_1_rdonly1.remove_tree()


class TestSplitCloneResiliency(unittest.TestCase):
  """Tests that the SplitClone worker is resilient to particular failures."""

  def _init_keyspace(self):
    """Creates a `test_keyspace` keyspace, and sets a sharding key."""
    utils.run_vtctl(['CreateKeyspace', 'test_keyspace'])
    utils.run_vtctl(['SetKeyspaceShardingInfo', 'test_keyspace',
                     'keyspace_id', KEYSPACE_ID_TYPE])

  def run_shard_tablets(self, shard_name, shard_tablets, create_db=True, create_table=True, wait_state='SERVING'):
    """Handles all the necessary work for initially running a shard's tablets.

    This encompasses the following steps:
      1. InitTablet for the appropriate tablets and types
      2. (optional) Create db
      3. Starting vttablets
      4. Waiting for the appropriate vttablet state
      5. Force reparent to the master tablet
      6. RebuildKeyspaceGraph
      7. (optional) Running initial schema setup

    Args:
      shard_name - the name of the shard to start tablets in
      shard_tablets - an instance of ShardTablets for the given shard
      wait_state - string, the vttablet state that we should wait for
      create_db - boolean, True iff we should create a db on the tablets
      create_table - boolean, True iff we should create a table on the tablets
    """
    shard_tablets.master.init_tablet('master', 'test_keyspace', shard_name)
    for tablet in shard_tablets.replicas:
      tablet.init_tablet('replica', 'test_keyspace', shard_name)
    for tablet in shard_tablets.rdonlys:
      tablet.init_tablet('rdonly', 'test_keyspace', shard_name)

    # Start tablets (and possibly create databases)
    for tablet in shard_tablets.all_tablets:
      if create_db:
        tablet.create_db('vt_test_keyspace')
      tablet.start_vttablet(wait_for_state=None)

    # Wait for tablet state to change after starting all tablets. This allows
    # us to start all tablets at once, instead of sequentially waiting.
    for tablet in shard_tablets.all_tablets:
      tablet.wait_for_vttablet_state(wait_state)

    # Reparent to choose an initial master
    utils.run_vtctl(['ReparentShard', '-force', 'test_keyspace/%s' % shard_name,
                     shard_tablets.master.tablet_alias], auto_log=True)

    utils.run_vtctl(['RebuildKeyspaceGraph', 'test_keyspace'], auto_log=True)

    create_table_sql = (
      'create table worker_test('
      'id bigint unsigned,'
      'msg varchar(64),'
      'keyspace_id bigint(20) unsigned not null,'
      'primary key (id),'
      'index by_msg (msg)'
      ') Engine=InnoDB'
    )

    if create_table:
      utils.run_vtctl(['ApplySchemaKeyspace',
                       '-simple',
                       '-sql=' + create_table_sql,
                       'test_keyspace'],
                      auto_log=True)

  def _insert_value(self, tablet, id, msg, keyspace_id):
    """Inserts a value in the MySQL database along with the required routing comments.

    Args:
      tablet - the Tablet instance to insert into
      id - the value of `id` column
      msg - the value of `msg` column
      keyspace_id - the value of `keyspace_id` column
    """
    k = "%u" % keyspace_id
    tablet.mquery('vt_test_keyspace', [
        'begin',
        'insert into worker_test(id, msg, keyspace_id) values(%u, "%s", 0x%x) /* EMD keyspace_id:%s user_id:%u */' % (id, msg, keyspace_id, k, id),
        'commit'
        ], write=True)

  def insert_values(self, tablet, num_values, num_shards, offset=0, keyspace_id_range=2**64):
    """Inserts simple values, one for each potential shard.

    Each row is given a message that contains the shard number, so we can easily
    verify that the source and destination shards have the same data.

    Args:
      tablet - the Tablet instance to insert into
      num_values - the number of values to insert
      num_shards - the number of shards that we expect to have
      offset - amount that we should offset the `id`s by. This is useful for
        inserting values multiple times.
      keyspace_id_range - the number of distinct values that the keyspace id can have
    """
    shard_width = keyspace_id_range / num_shards
    shard_offsets = [i * shard_width for i in xrange(num_shards)]
    for i in xrange(num_values):
      for shard_num in xrange(num_shards):
        self._insert_value(tablet, shard_offsets[shard_num] + offset + i,
                            'msg-shard-%u' % shard_num,
                            shard_offsets[shard_num] + i)

  def assert_shard_data_equal(self, shard_num, source_tablet, destination_tablet):
    """Asserts that a shard's data is identical on source and destination tablets.

    Args:
      shard_num - the shard number of the shard that we want to verify the data of
      source_tablet - Tablet instance of the source shard
      destination_tablet - Tablet instance of the destination shard
    """
    select_query = 'select * from worker_test where msg="msg-shard-%s" order by id asc' % shard_num

    source_rows = source_tablet.mquery('vt_test_keyspace', select_query)
    destination_rows = destination_tablet.mquery('vt_test_keyspace', select_query)
    self.assertEqual(source_rows, destination_rows)

  def run_split_diff(self, keyspace_shard, source_tablets, destination_tablets):
    """Runs a vtworker SplitDiff on the given keyspace/shard, and then sets all
    former rdonly slaves back to rdonly.

    Args:
      keyspace_shard - keyspace/shard to run SplitDiff on (string)
      source_tablets - ShardTablets instance for the source shard
      destination_tablets - ShardTablets instance for the destination shard
    """
    logging.debug("Running vtworker SplitDiff for %s" % keyspace_shard)
    stdout, stderr = utils.run_vtworker(['-cell', 'test_nj', 'SplitDiff',
      keyspace_shard], auto_log=True)

    for shard_tablets in (source_tablets, destination_tablets):
      for tablet in shard_tablets.rdonlys:
        utils.run_vtctl(['ChangeSlaveType', tablet.tablet_alias, 'rdonly'],
          auto_log=True)

  def setUp(self):
    """Creates the necessary keyspace/shards, starts the tablets, and inserts some data."""
    self._init_keyspace()

    self.run_shard_tablets('0', shard_tablets)
    # create the split shards
    self.run_shard_tablets('-80', shard_0_tablets, create_db=False,
      create_table=False, wait_state='NOT_SERVING')
    self.run_shard_tablets('80-', shard_1_tablets, create_db=False,
      create_table=False, wait_state='NOT_SERVING')

    # Copy the schema to the destinattion shards
    for keyspace_shard in ('test_keyspace/-80', 'test_keyspace/80-'):
      utils.run_vtctl(['CopySchemaShard',
                       '--exclude_tables', 'unrelated',
                       shard_rdonly1.tablet_alias,
                       keyspace_shard],
                      auto_log=True)

    logging.debug("Start inserting initial data")
    self.insert_values(shard_master, 3000, 2)
    logging.debug("Done inserting initial data")

  def tearDown(self):
    """TODO(aaijazi): Should probably do the following:

    - Drop db
    - Scrap tablet
    - Delete tablets
    - Delete keyspace shards

    and test that it works reasonably fast.

    Might need to move init_keysace to a class setUp if it can't be reversed.
    """
    pass

  def test_reparent_during_worker_copy(self):
    """This test simulates a destination reparent during a worker SplitClone copy.

    The SplitClone command should be able to gracefully handle the reparent and
    end up with the correct data on the destination.

    Note: this test has a small possibility of flaking, due to the timing issues
    involved. It's possible for the worker to finish the copy step before the
    reparent succeeds, in which case there are assertions that will fail. This
    seems better than having the test silently pass.
    """
    worker_proc, worker_port = utils.run_vtworker_bg(['--cell', 'test_nj',
                        'SplitClone',
                        '--strategy=-populate_blp_checkpoint',
                        'test_keyspace/0'],
                       auto_log=True)

    utils.poll_for_vars('vtworker', worker_port,
      'WorkerDestinationActualResolves >= 1',
      condition_fn=lambda v: v.get('WorkerDestinationActualResolves') >= 1)

    utils.run_vtctl(['ReparentShard', 'test_keyspace/-80',
      shard_0_replica.tablet_alias], auto_log=True)
    utils.run_vtctl(['ReparentShard', 'test_keyspace/80-',
      shard_1_replica.tablet_alias], auto_log=True)

    worker_vars = utils.poll_for_vars('vtworker', worker_port,
      'WorkerState == cleaning up',
      condition_fn=lambda v: v.get('WorkerState') == 'cleaning up')

    # Verify that we were forced to reresolve and retry.
    self.assertGreater(worker_vars['WorkerDestinationActualResolves'], 1)
    self.assertGreater(worker_vars['WorkerDestinationAttemptedResolves'], 1)
    self.assertNotEqual(worker_vars['WorkerRetryCount'], {},
      "expected vtworker to retry, but it didn't")

    utils.wait_procs([worker_proc])

    utils.run_vtctl(['ChangeSlaveType', shard_rdonly1.tablet_alias, 'rdonly'],
                     auto_log=True)

    # Make sure that everything is caught up to the same replication point
    self.run_split_diff('test_keyspace/-80', shard_tablets, shard_0_tablets)
    self.run_split_diff('test_keyspace/80-', shard_tablets, shard_1_tablets)

    self.assert_shard_data_equal(0, shard_master, shard_0_tablets.replica)
    self.assert_shard_data_equal(1, shard_master, shard_1_tablets.replica)

if __name__ == '__main__':
  utils.main()