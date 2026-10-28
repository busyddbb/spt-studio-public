// Public upload/editor controls, matching the Mac implementation. No network or credential APIs.
(args) => {
  if (/\/login(?:\/|$)/.test(location.pathname) || document.querySelector('input[placeholder="手机号"],input[placeholder="验证码"]')) return {status:'login'};
  if (args.phase === 'input') {
    const image = args.target === 'image';
    const all = Array.from(document.querySelectorAll('input.upload-input[type="file"]'));
    const found = all.filter(el => {
      const types = (el.accept || '').toLowerCase().split(',').map(t => t.trim());
      return image ? el.multiple && types.some(t => ['image/*','image/jpeg','image/png','.jpg','.jpeg','.png'].includes(t))
        : !el.multiple && types.some(t => ['video/*','video/mp4','video/quicktime','.mp4','.mov','.mkv','.flv','.f4v','.rm','.rmvb','.m4v','.mpg','.mpeg','.ts'].includes(t));
    });
    return found.length > 1 ? {status:'ambiguous'} : found.length === 1 ? {status:'ready',index:all.indexOf(found[0])} : {status:'wait'};
  }
  const ts = Array.from(document.querySelectorAll('input[placeholder="填写标题会有更多赞哦"],textarea[placeholder="填写标题会有更多赞哦"]'));
  const es = Array.from(document.querySelectorAll('.ProseMirror[contenteditable="true"]'));
  if (ts.length > 1 || es.length > 1) return {status:'ambiguous'};
  if (ts.length !== 1 || es.length !== 1) return {status:'wait'};
  const title = ts[0], editor = es[0], requestedTitle = args.title, requestedBody = args.body;
  if (title.disabled || title.readOnly) return {status:'wait'};
  const normalize = t => String(t).replace(/\r\n/g,'\n').replace(/\u00a0/g,' ').trim();
  if (title.maxLength > 0 && requestedTitle.length > title.maxLength) return {status:'too_long'};
  const previous = normalize(editor.innerText || editor.textContent || '');
  if ((title.value && title.value !== requestedTitle) || (previous && previous !== normalize(requestedBody))) return {status:'existing_content'};
  const proto = title.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto,'value').set.call(title,requestedTitle);
  title.dispatchEvent(new Event('input',{bubbles:true}));
  title.dispatchEvent(new Event('change',{bubbles:true}));
  if (previous !== normalize(requestedBody)) {
    editor.focus();
    const range = document.createRange(); range.selectNodeContents(editor);
    const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    if (!document.execCommand('insertText',false,requestedBody)) return {status:'editor_rejected'};
    editor.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:requestedBody}));
  }
  const read = n => n.nodeType === 3 ? n.textContent : n.tagName === 'BR' ? (/trailingBreak/.test(n.className || '') ? '' : '\n') : Array.from(n.childNodes).map(read).join('') + (/^(P|DIV)$/.test(n.tagName) ? '\n' : '');
  const actual = normalize(read(editor)), wanted = normalize(requestedBody);
  if (title.value !== requestedTitle || (actual !== wanted && actual.replace(/\n+/g,'\n') !== wanted.replace(/\n+/g,'\n'))) return {status:'editor_rejected'};
  return {status:'filled'};
}
