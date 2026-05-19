// Executes localized assertions for desktop
(function() {
  const results = {
    total: 0,
    failures: 0,
    cases: []
  };

  function assert(name, condition, message) {
    results.total++;
    if (!condition) {
      results.failures++;
      results.cases.push({ name, failed: true, message });
    } else {
      results.cases.push({ name, failed: false });
    }
  }

  try {
    // Test 1: Nav toggle visible
    const navToggle = document.querySelector('#nav-toggle');
    if (navToggle) {
      const isHidden = window.getComputedStyle(navToggle).display === 'none';
      assert("Hamburger visible on desktop", !isHidden, "Hamburger is hidden but should be visible on desktop to allow collapsing");
    } else {
      assert("Hamburger visible on desktop", false, "Hamburger element missing from DOM");
    }

    // Test 2: Sidebar visible
    const sidebar = document.querySelector('.sidebar');
    if (sidebar) {
      const box = sidebar.getBoundingClientRect();
      assert("Sidebar rendered and visible", box.width > 0, `Sidebar width is 0`);
    } else {
      assert("Sidebar rendered and visible", false, "Sidebar not found in DOM");
    }

    // Test 3: Data cards present
    const kpiElements = document.querySelectorAll('.kpi-row, .kpi');
    assert("KPI elements present", kpiElements.length > 0, "No KPI elements found");

  } catch (e) {
    assert("Test execution error", false, e.toString());
  }

  return results;
})();
