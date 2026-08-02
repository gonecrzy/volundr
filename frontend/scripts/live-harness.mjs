import net from "node:net";
import { pathToFileURL } from "node:url";

export const LOOPBACK_HOST = "127.0.0.1";

export function assertLoopbackHost(host) {
  if (host !== LOOPBACK_HOST && host !== "::1") {
    throw new Error(`Live E2E requires an explicit loopback host; received ${host}.`);
  }
}

export function normalizePort(value, label) {
  const port = Number(value ?? 0);
  if (!Number.isInteger(port) || port < 0 || port > 65535) {
    throw new Error(`${label} port must be an integer from 0 to 65535; received ${String(value)}.`);
  }
  return port;
}

export function formatBindFailure(label, port, error) {
  const code = error?.code ? ` (${error.code})` : "";
  return `Unable to bind the ${label} loopback port ${port}${code}: ${error?.message ?? String(error)}. ` +
    "Choose an unused configured port or leave the port unset for dynamic allocation; " +
    "the harness will not reuse an unrelated running server.";
}

async function reserveLoopbackPort(port, label) {
  const server = net.createServer();
  try {
    await new Promise((resolve, reject) => {
      const onError = (error) => {
        server.off("listening", onListening);
        reject(error);
      };
      const onListening = () => {
        server.off("error", onError);
        resolve();
      };
      server.once("error", onError);
      server.once("listening", onListening);
      server.listen({ host: LOOPBACK_HOST, port });
    });
    const address = server.address();
    if (!address || typeof address === "string") {
      throw new Error("the operating system did not return a TCP port");
    }
    return address.port;
  } catch (error) {
    throw new Error(formatBindFailure(label, port, error), { cause: error });
  } finally {
    await new Promise((resolve) => server.close(() => resolve()));
  }
}

export async function allocateLoopbackPorts({ apiPort = 0, webPort = 0 } = {}) {
  assertLoopbackHost(LOOPBACK_HOST);
  const normalizedApiPort = normalizePort(apiPort, "API");
  const normalizedWebPort = normalizePort(webPort, "web");
  const resolvedApiPort = await reserveLoopbackPort(normalizedApiPort, "API");
  const resolvedWebPort = await reserveLoopbackPort(normalizedWebPort, "web");
  if (resolvedApiPort === resolvedWebPort) {
    throw new Error(`API and web ports must differ; both resolved to ${resolvedApiPort}.`);
  }
  return { host: LOOPBACK_HOST, apiPort: resolvedApiPort, webPort: resolvedWebPort };
}

async function main() {
  const ports = await allocateLoopbackPorts({
    apiPort: process.argv[2] ?? process.env.VOLUNDR_E2E_API_PORT ?? 0,
    webPort: process.argv[3] ?? process.env.VOLUNDR_E2E_WEB_PORT ?? 0,
  });
  process.stdout.write(`${JSON.stringify(ports)}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}
