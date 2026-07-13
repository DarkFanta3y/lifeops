import assert from "node:assert/strict";
import test from "node:test";

import {
  canLoadMore,
  isCurrentGeneration,
  mergeUniqueById,
  prependUniqueById,
  restorePrependScrollPosition,
} from "./pagination.js";

test("append pagination deduplicates stable IDs", () => {
  const result = mergeUniqueById(
    [{ conversation_id: "a" }, { conversation_id: "b" }],
    [{ conversation_id: "b" }, { conversation_id: "c" }],
    "conversation_id",
  );
  assert.deepEqual(result.map((item) => item.conversation_id), ["a", "b", "c"]);
});

test("prepend pagination deduplicates and keeps chronological order", () => {
  const result = prependUniqueById(
    [{ message_id: 3 }, { message_id: 4 }],
    [{ message_id: 1 }, { message_id: 2 }, { message_id: 3 }],
    "message_id",
  );
  assert.deepEqual(result.map((item) => item.message_id), [1, 2, 3, 4]);
});

test("prepend scroll restoration preserves the visible anchor", () => {
  const element = { scrollHeight: 760, scrollTop: 40 };
  restorePrependScrollPosition(element, 500, 40);
  assert.equal(element.scrollTop, 300);
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
