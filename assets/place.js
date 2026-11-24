// On Android, "Deschide în aplicația Biserici" opens this place in the app, or Google Play without it.
(function () {
  var a = document.getElementById("open");
  if (a && /Android/i.test(navigator.userAgent) && a.dataset.intent) a.href = a.dataset.intent;
})();
