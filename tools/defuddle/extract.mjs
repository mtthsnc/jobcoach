import { JSDOM } from "jsdom";
import { Defuddle } from "defuddle";

function exitWithError(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

const [url] = process.argv.slice(2);
if (!url) {
  exitWithError("usage: extract.mjs <url>");
}

function installDomGlobals(window) {
  const keys = [
    "window",
    "document",
    "Node",
    "NodeFilter",
    "Element",
    "HTMLElement",
    "HTMLImageElement",
    "HTMLVideoElement",
    "HTMLIFrameElement",
    "HTMLAnchorElement",
    "HTMLTableElement",
    "SVGElement",
    "DOMParser",
    "Text",
    "Comment",
    "getComputedStyle",
  ];
  const previous = new Map();
  for (const key of keys) {
    previous.set(key, globalThis[key]);
    if (window[key] !== undefined) {
      globalThis[key] = window[key];
    }
  }
  return () => {
    for (const key of keys) {
      const prior = previous.get(key);
      if (prior === undefined) {
        delete globalThis[key];
      } else {
        globalThis[key] = prior;
      }
    }
  };
}

try {
  const response = await fetch(url, {
    headers: {
      "user-agent":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
      "accept-language": "en-US,en;q=0.9,da-DK;q=0.8,da;q=0.7",
    },
  });
  if (!response.ok) {
    throw new Error(`http_status_${response.status}`);
  }
  const html = await response.text();
  const dom = new JSDOM(html, { url });
  const restoreGlobals = installDomGlobals(dom.window);
  let result;
  try {
    result = new Defuddle(dom.window.document).parse();
  } finally {
    restoreGlobals();
  }
  const payload = {
    title: typeof result?.title === "string" ? result.title : "",
    content: typeof result?.content === "string" ? result.content : "",
  };
  process.stdout.write(JSON.stringify(payload));
} catch (error) {
  const reason = error instanceof Error ? error.message : String(error);
  exitWithError(`defuddle_error: ${reason}`);
}
