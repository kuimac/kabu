(function () {
  function readJson(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  var data = readJson("chart-data") || {};

  var ink = "#e8f2ee";
  var muted = "#9bb5ac";
  var grid = "rgba(232, 242, 238, 0.08)";
  var accent = "#3ecf8e";
  var neg = "#ff7b72";

  Chart.defaults.color = muted;
  Chart.defaults.font.family = '"IBM Plex Sans JP", "IBM Plex Sans", sans-serif';
  Chart.defaults.borderColor = grid;

  var allocCanvas = document.getElementById("allocChart");
  if (allocCanvas && data.allocationLabels) {
    new Chart(allocCanvas, {
      type: "doughnut",
      data: {
        labels: data.allocationLabels,
        datasets: [{
          data: data.allocationValues,
          backgroundColor: [
            "#3ecf8e", "#f0c35a", "#6ec6ff", "#ff9f7a", "#b7a0ff", "#7ddea2", "#e8d39b"
          ],
          borderWidth: 0
        }]
      },
      options: {
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 12, color: ink } }
        },
        cutout: "58%"
      }
    });
  }

  var pnlCanvas = document.getElementById("pnlChart");
  if (pnlCanvas && data.pnlLabels) {
    new Chart(pnlCanvas, {
      type: "bar",
      data: {
        labels: data.pnlLabels,
        datasets: [{
          data: data.pnlValues,
          backgroundColor: data.pnlValues.map(function (v) {
            return v >= 0 ? accent : neg;
          }),
          borderRadius: 6
        }]
      },
      options: {
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { maxRotation: 45, minRotation: 0 } },
          y: { grid: { color: grid } }
        }
      }
    });
  }

  var priceCanvas = document.getElementById("priceChart");
  if (priceCanvas && data.priceLabels) {
    new Chart(priceCanvas, {
      type: "line",
      data: {
        labels: data.priceLabels,
        datasets: [{
          data: data.priceValues,
          borderColor: accent,
          backgroundColor: "rgba(62, 207, 142, 0.16)",
          pointBackgroundColor: accent,
          pointRadius: data.priceLabels.length > 60 ? 0 : 4,
          tension: 0.15,
          fill: true
        }]
      },
      options: {
        plugins: { legend: { display: false } },
        scales: {
          x: {
            title: { display: true, text: "記録日", color: muted },
            ticks: { maxRotation: 0, minRotation: 0, maxTicksLimit: 8, autoSkip: true }
          },
          y: { grid: { color: grid } }
        }
      }
    });
  }
})();
