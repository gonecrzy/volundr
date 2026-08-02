import assert from "node:assert/strict";
import net from "node:net";
import test from "node:test";

import {
  allocateLoopbackPorts,
  assertLoopbackHost,
  formatBindFailure,
} from "./live-harness.mjs";

test("allocates distinct loopback API and web ports", async () => {
  const ports = await allocateLoopbackPorts({ apiPort: 0, webPort: 0 });

  assert.equal(ports.host, "127.0.0.1");
  assert.notEqual(ports.apiPort, ports.webPort);
  assert.ok(ports.apiPort > 0);
  assert.ok(ports.webPort > 0);
});

test("rejects non-loopback hosts", () => {
  assert.throws(() => assertLoopbackHost("0.0.0.0"), /explicit loopback host/);
  assert.doesNotThrow(() => assertLoopbackHost("127.0.0.1"));
});

test("reports configured-port bind failures without hiding the cause", async () => {
  const blocker = net.createServer();
  await new Promise((resolve) => blocker.listen(0, "127.0.0.1", resolve));
  const address = blocker.address();
  assert.ok(address && typeof address !== "string");

  await assert.rejects(
    allocateLoopbackPorts({ apiPort: address.port, webPort: 0 }),
    (error) => {
      assert.match(formatBindFailure("api", address.port, error), /api/);
      assert.ok(formatBindFailure("api", address.port, error).includes(String(address.port)));
      return true;
    },
  );
  await new Promise((resolve) => blocker.close(resolve));
});
