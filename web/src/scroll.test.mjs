import assert from "node:assert/strict";
import test from "node:test";

import { isNearBottom } from "./scroll.js";

test("isNearBottom treats positions within the threshold as near the bottom", () => {
  assert.equal(
    isNearBottom({
      scrollTop: 520,
      clientHeight: 400,
      scrollHeight: 1000,
    }),
    true,
  );
});

test("isNearBottom treats positions beyond the threshold as away from the bottom", () => {
  assert.equal(
    isNearBottom({
      scrollTop: 500,
      clientHeight: 400,
      scrollHeight: 1000,
    }),
    false,
  );
});

test("isNearBottom supports a custom threshold", () => {
  assert.equal(
    isNearBottom(
      {
        scrollTop: 500,
        clientHeight: 400,
        scrollHeight: 1000,
      },
      120,
    ),
    true,
  );
});
