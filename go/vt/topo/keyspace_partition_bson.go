// Copyright 2012, Google Inc. All rights reserved.
// Use of this source code is governed by a BSD-style
// license that can be found in the LICENSE file.

package topo

// DO NOT EDIT.
// FILE GENERATED BY BSONGEN.

import (
	"bytes"

	"github.com/youtube/vitess/go/bson"
	"github.com/youtube/vitess/go/bytes2"
)

// MarshalBson bson-encodes KeyspacePartition.
func (keyspacePartition *KeyspacePartition) MarshalBson(buf *bytes2.ChunkedWriter, key string) {
	bson.EncodeOptionalPrefix(buf, bson.Object, key)
	lenWriter := bson.NewLenWriter(buf)

	// []SrvShard
	{
		bson.EncodePrefix(buf, bson.Array, "Shards")
		lenWriter := bson.NewLenWriter(buf)
		for _i, _v1 := range keyspacePartition.Shards {
			_v1.MarshalBson(buf, bson.Itoa(_i))
		}
		lenWriter.Close()
	}
	// []ShardReference
	{
		bson.EncodePrefix(buf, bson.Array, "ShardReferences")
		lenWriter := bson.NewLenWriter(buf)
		for _i, _v2 := range keyspacePartition.ShardReferences {
			_v2.MarshalBson(buf, bson.Itoa(_i))
		}
		lenWriter.Close()
	}

	lenWriter.Close()
}

// UnmarshalBson bson-decodes into KeyspacePartition.
func (keyspacePartition *KeyspacePartition) UnmarshalBson(buf *bytes.Buffer, kind byte) {
	switch kind {
	case bson.EOO, bson.Object:
		// valid
	case bson.Null:
		return
	default:
		panic(bson.NewBsonError("unexpected kind %v for KeyspacePartition", kind))
	}
	bson.Next(buf, 4)

	for kind := bson.NextByte(buf); kind != bson.EOO; kind = bson.NextByte(buf) {
		switch bson.ReadCString(buf) {
		case "Shards":
			// []SrvShard
			if kind != bson.Null {
				if kind != bson.Array {
					panic(bson.NewBsonError("unexpected kind %v for keyspacePartition.Shards", kind))
				}
				bson.Next(buf, 4)
				keyspacePartition.Shards = make([]SrvShard, 0, 8)
				for kind := bson.NextByte(buf); kind != bson.EOO; kind = bson.NextByte(buf) {
					bson.SkipIndex(buf)
					var _v1 SrvShard
					_v1.UnmarshalBson(buf, kind)
					keyspacePartition.Shards = append(keyspacePartition.Shards, _v1)
				}
			}
		case "ShardReferences":
			// []ShardReference
			if kind != bson.Null {
				if kind != bson.Array {
					panic(bson.NewBsonError("unexpected kind %v for keyspacePartition.ShardReferences", kind))
				}
				bson.Next(buf, 4)
				keyspacePartition.ShardReferences = make([]ShardReference, 0, 8)
				for kind := bson.NextByte(buf); kind != bson.EOO; kind = bson.NextByte(buf) {
					bson.SkipIndex(buf)
					var _v2 ShardReference
					_v2.UnmarshalBson(buf, kind)
					keyspacePartition.ShardReferences = append(keyspacePartition.ShardReferences, _v2)
				}
			}
		default:
			bson.Skip(buf, kind)
		}
	}
}
