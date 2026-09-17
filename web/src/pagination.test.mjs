import assert from "node:assert/strict";
import test from "node:test";

import {
  canLoadMore,
  isCurrentGeneration,
  mergeUniqueById,
} from "./pagination.js";

test("append pagination deduplicates stable IDs", () => {
  const result = mergeUniqueById(
    [{ conversation_id: "a" }, { conversation_id: "b" }],
    [{ conversation_id: "b" }, { conversation_id: "c" }],
    "conversation_id",
  );
  assert.deepEqual(result.map((item) => item.conversation_id), ["a", "b", "c"]);
});

test("request generations reject responses from an old query or conversation", () => {
  assert.equal(isCurrentGeneration(4, 5), false);
  assert.equal(isCurrentGeneration(5, 5), true);
});

test("pagination stops requesting after has_more becomes false", () => {
  assert.equal(canLoadMore(false, false), false);
  assert.equal(canLoadMore(true, true), false);
  assert.equal(canLoadMore(true, false), true);
});
