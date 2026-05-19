// Orchestrates the UI tests
const dashboards = [
  { name: "rita", url: "http://localhost:8000/dashboard/rita.html" },
  { name: "fno", url: "http://localhost:8000/dashboard/fno.html" },
  { name: "ops", url: "http://localhost:8000/dashboard/ops.html" }
];

let testResults = {
  total: 0,
  failures: 0,
  cases: []
};

function generateJunitXML(results) {
  const timestamp = new Date().toISOString();
  let xml = `<?xml version="1.0" encoding="utf-8"?>\n`;
  xml += `<testsuites>\n`;
  xml += `  <testsuite name="Chrome UI Tests" errors="0" failures="${results.failures}" skipped="0" tests="${results.total}" time="0" timestamp="${timestamp}" hostname="chrome-plugin">\n`;
  
  for (const tc of results.cases) {
    xml += `    <testcase classname="ui" name="${tc.name}" time="0">\n`;
    if (tc.failed) {
      xml += `      <failure message="${tc.message}">${tc.message}</failure>\n`;
    }
    xml += `    </testcase>\n`;
  }
  
  xml += `  </testsuite>\n`;
  xml += `</testsuites>`;
  return xml;
}

async function runTestsForTab(tabId, url, name) {
  // Use Chrome debugger to set device metrics to 1280x800 desktop
  await chrome.debugger.attach({ tabId: tabId }, "1.3");
  await chrome.debugger.sendCommand({ tabId: tabId }, "Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 800,
    deviceScaleFactor: 1,
    mobile: false
  });

  // Navigate and wait for load
  await chrome.tabs.update(tabId, { url: url });
  await new Promise(resolve => {
    chrome.tabs.onUpdated.addListener(function listener(tId, info) {
      if (tId === tabId && info.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);
        setTimeout(resolve, 800); // give it time to render DOM and execute scripts fully
      }
    });
  });

  // Inject content script to run tests
  const injection = await chrome.scripting.executeScript({
    target: { tabId: tabId },
    files: ["content.js"]
  });

  // Detach debugger to restore user window state
  await chrome.debugger.detach({ tabId: tabId });

  if (injection && injection[0] && injection[0].result) {
    const res = injection[0].result;
    testResults.total += res.total;
    testResults.failures += res.failures;
    for (const tc of res.cases) {
      // Prefix test name with dashboard name
      tc.name = `[${name.toUpperCase()}] ${tc.name}`;
      testResults.cases.push(tc);
    }
  } else {
    testResults.total += 1;
    testResults.failures += 1;
    testResults.cases.push({ name: `[${name}] Execution`, failed: true, message: "Content script did not return results" });
  }
}

chrome.action.onClicked.addListener(async (tab) => {
  // Reset
  testResults = { total: 0, failures: 0, cases: [] };

  for (const db of dashboards) {
    try {
      await runTestsForTab(tab.id, db.url, db.name);
    } catch (e) {
      testResults.total += 1;
      testResults.failures += 1;
      testResults.cases.push({ name: `[${db.name}] Setup`, failed: true, message: e.message || "Failed to setup test" });
    }
  }

  // Generate XML and trigger download dialog
  const xml = generateJunitXML(testResults);
  const dataUrl = "data:application/xml;charset=utf-8," + encodeURIComponent(xml);
  
  chrome.downloads.download({
    url: dataUrl,
    filename: "latest.xml",
    saveAs: true // Prompts the user to save it directly into test-results/ui/
  });
});
