/* VOX Editor — service worker mínimo (v1.15.2).
   Serve só para o celular oferecer "Instalar app". Não guarda a tela nem os vídeos:
   tudo continua vindo do servidor, então as atualizações aparecem na hora. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  if (e.request.mode !== "navigate") return;  // vídeos, envios e a API passam direto, sem tocar
  e.respondWith(fetch(e.request).catch(() => new Response(
    '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<body style="background:#0e0f13;color:#eee;font:16px system-ui;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;padding:20px">' +
    '<div><h2>Sem internet</h2><p>O VOX Editor precisa de conexão. Confira a internet e toque para tentar de novo.</p>' +
    '<button onclick="location.reload()" style="font:inherit;padding:10px 18px;border-radius:10px;border:0;background:#1d8cf8;color:#fff">Tentar de novo</button></div>',
    { headers: { "Content-Type": "text/html; charset=utf-8" } })));
});
