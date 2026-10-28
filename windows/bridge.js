/* SPT's existing UI protocol, available only in the local application window. */
(() => {
  'use strict';
  if (location.origin !== 'http://127.0.0.1:8766') return;
  if (window.parent !== window) {
    try {
      if (window.parent.location.origin !== location.origin) return;
      window.webkit = {messageHandlers: window.parent.webkit.messageHandlers};
      for (const flag of ['mediaNativeAvailable','mediaPublishingNativeAvailable','mediaRednoteUploadNativeAvailable','mediaPublishingQueueNativeAvailable','mediaMetricsReaderAvailable']) window[flag] = true;
    } catch (_) { /* An external frame receives no local bridge. */ }
    return;
  }
  if (typeof window.sptWindowsBridge !== 'function') return;
  const names = ['openPublishing','runPublishingQueue','previewPublishingQueue','startRednoteUpload','cancelRednoteUpload','previewRednoteUpload','chooseWorkspace','chooseMedia'];
  const handlers = {};
  for (const command of names) handlers[command] = {postMessage(payload = {}) {
    return window.sptWindowsBridge(command, command === 'runPublishingQueue' ? {} : payload).catch(error => {
      const message = String(error?.message || 'Windows 执行器未完成操作');
      if (command === 'openPublishing') window.mediaPublishingOpenResult?.({ok:false,error:message});
      else if (/RednoteUpload/.test(command)) window.mediaNativeUploadStatus?.({id:payload.job_id||'',state:'needs_attention',message});
      else window.dispatchEvent(new CustomEvent('spt-windows-error',{detail:{command,message}}));
    });
  }};
  window.webkit = {messageHandlers: handlers};
  for (const flag of ['mediaNativeAvailable','mediaPublishingNativeAvailable','mediaRednoteUploadNativeAvailable','mediaPublishingQueueNativeAvailable','mediaMetricsReaderAvailable']) window[flag] = true;
})();
