// =========================================================================
// Gestión de Incidentes - cambio de estado en línea (RF-005, Fase 2)
// =========================================================================
(function () {
  'use strict';

  function getCookie(name) {
    var v = null;
    if (document.cookie) {
      document.cookie.split(';').forEach(function (c) {
        var t = c.trim();
        if (t.indexOf(name + '=') === 0) v = decodeURIComponent(t.substring(name.length + 1));
      });
    }
    return v;
  }

  var toastEl = null;
  var toastTimer = null;
  function toast(msg, esError) {
    if (!toastEl) toastEl = document.getElementById('incToast');
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.className = 'inc-toast show' + (esError ? ' error' : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.className = 'inc-toast'; }, 3000);
  }

  // Mantiene la clase de color del select sincronizada con el estado elegido.
  function aplicarColor(select) {
    select.classList.remove('inc-estado-reportado', 'inc-estado-en_proceso', 'inc-estado-resuelta');
    select.classList.add('inc-estado-' + select.value.toLowerCase());
  }

  function iniciar() {
    var selects = document.querySelectorAll('.inc-estado-select');
    selects.forEach(function (select) {
      select.addEventListener('change', function () {
        var postId = select.getAttribute('data-post-id');
        var anterior = select.getAttribute('data-estado-actual');
        var nuevo = select.value;
        if (nuevo === anterior) return;

        select.disabled = true;
        var body = new URLSearchParams();
        body.append('estado', nuevo);

        fetch('/feed/publicacion/' + postId + '/cambiar-estado/', {
          method: 'POST',
          headers: {
            'X-CSRFToken': getCookie('csrftoken'),
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: body.toString(),
        })
          .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
          .then(function (res) {
            if (res.ok && res.data.status === 'ok') {
              select.setAttribute('data-estado-actual', nuevo);
              aplicarColor(select);
              toast(res.data.message || 'Estado actualizado.');
            } else {
              // Revertir al estado anterior si el servidor rechazó el cambio
              select.value = anterior;
              aplicarColor(select);
              toast((res.data && res.data.message) || 'No se pudo actualizar el estado.', true);
            }
          })
          .catch(function () {
            select.value = anterior;
            aplicarColor(select);
            toast('Error de conexión al actualizar el estado.', true);
          })
          .finally(function () { select.disabled = false; });
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else {
    iniciar();
  }
})();
