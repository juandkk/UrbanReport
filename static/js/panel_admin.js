// =========================================================================
// Panel de Control Municipal - Gráficas con Chart.js
// Lee los datos inyectados por Django (json_script) y dibuja las gráficas.
// =========================================================================
(function () {
  'use strict';

  function leerJSON(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  // Paleta coherente con el tema oscuro del portal
  var COLORS = {
    azul: '#3b82f6',
    verde: '#22c55e',
    ambar: '#f59e0b',
    rojo: '#ef4444',
    indigo: '#6366f1',
    cian: '#06b6d4',
    grid: 'rgba(148, 163, 184, 0.12)',
    texto: '#94a3b8',
  };

  function iniciar() {
    if (typeof Chart === 'undefined') {
      // Chart.js aún no cargó; reintentar brevemente.
      return setTimeout(iniciar, 60);
    }

    // Estilos globales
    Chart.defaults.color = COLORS.texto;
    Chart.defaults.font.family = "'Inter', system-ui, sans-serif";

    // --- Dona: reportes por categoría ---
    var catLabels = leerJSON('data-cat-labels');
    var catData = leerJSON('data-cat-data');
    var elCat = document.getElementById('chartCategoria');
    if (elCat && catLabels && catData) {
      new Chart(elCat, {
        type: 'doughnut',
        data: {
          labels: catLabels,
          datasets: [{
            data: catData,
            backgroundColor: [COLORS.azul, COLORS.ambar, COLORS.verde, COLORS.indigo, COLORS.cian, COLORS.rojo],
            borderColor: '#0f172a',
            borderWidth: 2,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '60%',
          plugins: {
            legend: { position: 'bottom', labels: { padding: 14, boxWidth: 12 } },
          },
        },
      });
    }

    // --- Barras: reportes por estado ---
    var estLabels = leerJSON('data-est-labels');
    var estData = leerJSON('data-est-data');
    var elEst = document.getElementById('chartEstado');
    if (elEst && estLabels && estData) {
      new Chart(elEst, {
        type: 'bar',
        data: {
          labels: estLabels,
          datasets: [{
            label: 'Reportes',
            data: estData,
            backgroundColor: [COLORS.ambar, COLORS.azul, COLORS.verde],
            borderRadius: 6,
            maxBarThickness: 56,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { display: false } },
            y: { beginAtZero: true, grid: { color: COLORS.grid }, ticks: { precision: 0 } },
          },
        },
      });
    }

    // --- Línea: tendencia de reportes (14 días) ---
    var tendLabels = leerJSON('data-tend-labels');
    var tendData = leerJSON('data-tend-data');
    var elTend = document.getElementById('chartTendencia');
    if (elTend && tendLabels && tendData) {
      new Chart(elTend, {
        type: 'line',
        data: {
          labels: tendLabels,
          datasets: [{
            label: 'Reportes nuevos',
            data: tendData,
            borderColor: COLORS.azul,
            backgroundColor: 'rgba(59, 130, 246, 0.15)',
            fill: true,
            tension: 0.35,
            pointRadius: 3,
            pointBackgroundColor: COLORS.azul,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { display: false } },
            y: { beginAtZero: true, grid: { color: COLORS.grid }, ticks: { precision: 0 } },
          },
        },
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else {
    iniciar();
  }
})();
