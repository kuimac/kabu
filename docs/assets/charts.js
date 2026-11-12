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

  function movingAverage(values, length) {
    var out = [];
    var sum = 0;
    for (var i = 0; i < values.length; i++) {
      var value = Number(values[i]);
      if (!isFinite(value)) {
        out.push(null);
        continue;
      }
      sum += value;
      if (i >= length) {
        var dropped = Number(values[i - length]);
        if (isFinite(dropped)) sum -= dropped;
      }
      out.push(i >= length - 1 ? sum / length : null);
    }
    return out;
  }

  function hasNumber(values) {
    for (var i = 0; i < values.length; i++) {
      if (values[i] != null && isFinite(values[i])) return true;
    }
    return false;
  }

  var priceCanvas = document.getElementById("priceChart");
  if (priceCanvas && data.priceLabels && data.priceValues) {
    var averages = [
      { label: "5日", length: 5, color: "#f0c35a" },
      { label: "25日", length: 25, color: "#6ec6ff" },
      { label: "75日", length: 75, color: "#ff9f7a" },
      { label: "200日", length: 200, color: "#b7a0ff" }
    ];
    var drewAverage = false;
    var datasets = [{
      label: "終値",
      data: data.priceValues,
      borderColor: accent,
      backgroundColor: "rgba(62, 207, 142, 0.16)",
      pointBackgroundColor: accent,
      pointRadius: data.priceLabels.length > 60 ? 0 : 4,
      tension: 0.15,
      fill: true
    }];
    averages.forEach(function (item) {
      var series = movingAverage(data.priceValues, item.length);
      if (!hasNumber(series)) return;
      drewAverage = true;
      datasets.push({
        label: item.label,
        data: series,
        borderColor: item.color,
        backgroundColor: "transparent",
        pointRadius: 0,
        borderWidth: 1.5,
        tension: 0,
        fill: false,
        spanGaps: false
      });
    });
    var card = priceCanvas.closest(".chart-card");
    if (card && drewAverage) {
      var heading = card.querySelector("h3");
      if (heading && heading.textContent.indexOf("移動平均") === -1) {
        heading.textContent = heading.textContent + "と移動平均";
      }
      var note = card.querySelector("p.muted");
      if (note && note.textContent.indexOf("75日・200日") === -1) {
        note.textContent += " 5日・25日・75日・200日の移動平均は、保存済みの日次終値から計算しています。";
      }
    }
    new Chart(priceCanvas, {
      type: "line",
      data: {
        labels: data.priceLabels,
        datasets: datasets
      },
      options: {
        plugins: {
          legend: {
            display: true,
            position: "bottom",
            labels: { boxWidth: 12, color: ink }
          }
        },
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
