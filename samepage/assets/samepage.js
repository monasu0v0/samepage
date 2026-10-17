(function(){
  var CFG = window.SAMEPAGE_CONFIG || {};
  var STORAGE_KEY = CFG.storageKey || "samepage:default";
  var JUMP_MODE = CFG.jump === "hash" ? "hash" : "scroll";
  var DOC_ID = CFG.doc || "default";
  var RESPONSES = (window.SAMEPAGE_RESPONSES && Array.isArray(window.SAMEPAGE_RESPONSES.responses)) ? window.SAMEPAGE_RESPONSES.responses : [];
  var QUESTIONS = (window.SAMEPAGE_QUESTIONS && Array.isArray(window.SAMEPAGE_QUESTIONS.questions)) ? window.SAMEPAGE_QUESTIONS.questions : [];
  var ANSWERS_KEY = 'samepage-answers:' + DOC_ID;

  var badge = document.getElementById('spBadge');
  var selectBtn = document.getElementById('spSelectBtn');
  var popup = document.getElementById('spPopup');
  var popupText = document.getElementById('spPopupText');
  var popupSave = document.getElementById('spPopupSave');
  var popupCancel = document.getElementById('spPopupCancel');
  var panel = document.getElementById('spPanel');
  var panelClose = document.getElementById('spPanelClose');
  var panelCount = document.getElementById('spPanelCount');
  var panelList = document.getElementById('spPanelList');
  var jsonBtn = document.getElementById('spJsonBtn');
  var jsonCopyDirectBtn = document.getElementById('spJsonCopyDirect');
  var jsonModal = document.getElementById('spJsonModal');
  var jsonOverlay = jsonModal.querySelector('.sp-json-overlay');
  var jsonText = document.getElementById('spJsonText');
  var jsonCopyBtn = document.getElementById('spJsonCopy');
  var jsonCloseBtn = document.getElementById('spJsonClose');
  var docCommentBtn = document.getElementById('spDocCommentBtn');
  var popupChips = document.getElementById('spPopupChips');
  var popupAddTarget = document.getElementById('spPopupAddTarget');
  var popupPalette = document.getElementById('spPopupPalette');
  var popupGuide = document.getElementById('spPopupGuide');
  var panelQuestions = document.getElementById('spPanelQuestions');

  var comments = [];
  var pendingSelection = null;   // text selection just made, popup not shown yet (waiting on selectBtn/'a')
  var pendingTargets = [];       // targets collected while the popup is open: {unit, unitLabel, target}
  var pendingAction = null;      // action chosen from the verb palette (move/insert/delete/shorten/keep)
  var ACTION_LABEL = {move:'Move', insert:'Insert', 'delete':'Delete', shorten:'Shorten', keep:'Keep 👍'};
  var popupOpen = false;
  var editingId = null;
  var addTargetHintTimer = null;

  // ---- IME composition detection (avoid confusing a confirming Enter with a submit Enter) ----
  // isComposing / keyCode===229 can be missing or wrong in some environments, so we also keep
  // our own flag driven by compositionstart/compositionend as a last resort. These aren't keydown
  // events, so they are unaffected by the keydown capture handler's stopPropagation below and can
  // be safely picked up via a document-level capture listener.
  var imeComposing = false;
  document.addEventListener('compositionstart', function(){ imeComposing = true; }, true);
  document.addEventListener('compositionend', function(){ imeComposing = false; }, true);
  function isImeComposing(e){
    return imeComposing || e.isComposing === true || e.keyCode === 229;
  }

  function cssEsc(s){
    if(window.CSS && CSS.escape) return CSS.escape(s);
    return String(s).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  }
  function truncate(s, n){
    s = s || '';
    return s.length > n ? s.slice(0, n) + '…' : s;
  }
  function randomId8(){
    var out = '';
    for(var i=0;i<8;i++){ out += Math.floor(Math.random()*36).toString(36); }
    return out;
  }

  // ---- unit lookup (host-agnostic: relies only on [data-sp-unit]) ----
  function unitElement(unit){
    if(!unit) return null;
    var sel = '[data-sp-unit="' + cssEsc(unit) + '"]';
    return document.querySelector(sel);
  }
  function unitInfoFor(node){
    var el = node && node.closest ? node.closest('[data-sp-unit]') : null;
    if(!el) return null;
    return {
      unit: el.getAttribute('data-sp-unit'),
      unitLabel: el.getAttribute('data-sp-label') || el.getAttribute('data-sp-unit'),
      el: el
    };
  }
  function jumpToUnit(unit){
    var el = unitElement(unit);
    if(!el) return;
    var index = el.getAttribute('data-sp-index');
    if(JUMP_MODE === 'hash' && index){
      location.hash = '#' + index;   // delegate to the host page's own hashchange routing
    } else {
      el.scrollIntoView({behavior:'smooth', block:'start'});
    }
  }

  // ---- element path (nth-of-type chain; independent of id/class) ----
  function cssPath(el){
    var parts = [];
    while(el && el.nodeType===1 && el!==document.body && el!==document.documentElement){
      var tag = el.tagName.toLowerCase();
      var idx = 1, sib = el;
      while((sib = sib.previousElementSibling)){
        if(sib.tagName===el.tagName) idx++;
      }
      parts.unshift(tag + ':nth-of-type(' + idx + ')');
      el = el.parentElement;
    }
    return 'body' + (parts.length ? ' > ' + parts.join(' > ') : '');
  }
  function nearTextOf(el){
    if(!el) return '';
    return (el.textContent||'').replace(/\s+/g,' ').trim().slice(0,60);
  }
  function resolveByPath(path, tag, nearText){
    var el = null;
    if(path){
      try{ el = document.querySelector(path); }catch(e){ el = null; }
    }
    if(el) return el;
    // fallback: search elements of the same tag for a nearText match
    if(!tag || !nearText) return null;
    var cands = document.getElementsByTagName(tag);
    for(var i=0;i<cands.length;i++){
      if(cands[i].closest('#spPanel,#spPopup,#spJsonModal')) continue;
      if(nearTextOf(cands[i]) === nearText) return cands[i];
    }
    return null;
  }

  // ---- diagram node (a node inside an SVG diagram; data-sp-node is used as a stable id) ----
  // An nth-of-type chain (cssPath) shifts entirely once the diagram regenerates with one more
  // node, but a semantic id assigned by the generator (data-sp-node) survives layout changes.
  var SVG_NS = 'http://www.w3.org/2000/svg';
  function isSvgEl(el){
    return !!(el && el.namespaceURI === SVG_NS);
  }
  function insideSvg(node){
    var el = node && node.nodeType===3 ? node.parentElement : node;
    return isSvgEl(el);
  }
  function diagramNodeOf(el){
    return el && el.closest ? el.closest('[data-sp-node]') : null;
  }
  // nearText for a node. Don't mix in text from runtime decorations (question pins, halo).
  function diagramNearText(el){
    var clone = el.cloneNode(true);
    var junk = clone.querySelectorAll('.sp-qpin-svg,.sp-node-halo');
    for(var i=0;i<junk.length;i++){ junk[i].parentNode.removeChild(junk[i]); }
    return (clone.textContent||'').replace(/\s+/g,' ').trim().slice(0,60);
  }
  function resolveDiagramNode(nodeId, nodeLabel){
    var el = nodeId ? document.querySelector('[data-sp-node="'+cssEsc(nodeId)+'"]') : null;
    if(el) return el;
    // fallback: match by label (in case nodeId changed on regeneration)
    if(!nodeLabel) return null;
    var cands = document.querySelectorAll('[data-sp-node]');
    for(var i=0;i<cands.length;i++){
      if((cands[i].getAttribute('data-sp-label')||'') === nodeLabel) return cands[i];
    }
    return null;
  }
  // Highlighting uses an overlaid SVG rect rather than a CSS outline (outline has no effect on
  // SVG elements). If the target is a container (g/svg) the rect is appended as a child so it
  // inherits the same coordinate system; if it's a leaf element the rect is appended to the
  // parent and the target's own transform is duplicated (getBBox does not include the element's
  // own transform).
  function svgOverlayHost(el){
    var tag = el.tagName.toLowerCase();
    return (tag==='g' || tag==='svg') ? el : el.parentNode;
  }
  function appendSvgOverlay(el, node){
    var host = svgOverlayHost(el);
    if(host !== el && el.getAttribute('transform')){
      node.setAttribute('transform', el.getAttribute('transform'));
    }
    host.appendChild(node);
    return node;
  }
  function svgHalo(el, cmtId, resolved){
    var box;
    try{ box = el.getBBox(); }catch(e){ return null; }
    var halo = document.createElementNS(SVG_NS, 'rect');
    halo.setAttribute('x', box.x - 4);
    halo.setAttribute('y', box.y - 4);
    halo.setAttribute('width', box.width + 8);
    halo.setAttribute('height', box.height + 8);
    halo.setAttribute('rx', 6);
    halo.setAttribute('class', 'sp-node-halo' + (resolved ? ' sp-node-halo-resolved' : ''));
    halo.setAttribute('data-sp-cmt-id', cmtId);
    return appendSvgOverlay(el, halo);
  }

  // ---- element pick mode (devtools-inspector style) ----
  var pickOutline = document.getElementById('spPickOutline');
  var pickLine = document.getElementById('spPickLine');
  var pickHint = document.getElementById('spPickHint');
  var PICK_HINT_DEFAULT = pickHint.textContent;
  var picking = null;   // {onPick: fn, onCancel: fn}; non-null only while active
  var EDGE = 8;         // within this many px of the top/bottom edge counts as an insertion point
  var pickBaseHit = null;  // the raw hit (the hovered element itself) picked up by the latest mousemove
  var pickLevel = 0;       // number of parent-escalation steps taken via up/down

  function climbToLevel(el, level){
    for(var i=0;i<level;i++){
      if(!el || el===document.body) break;
      if(!el.parentElement) break;
      el = el.parentElement;
    }
    return el;
  }
  function effectiveHit(){
    if(!pickBaseHit) return null;
    var el = climbToLevel(pickBaseHit.el, pickLevel);
    var where = (pickLevel===0) ? pickBaseHit.where : null;
    return {el:el, where:where};
  }
  function updatePickHintForLevel(){
    if(pickLevel===0 || !pickBaseHit){ pickHint.textContent = PICK_HINT_DEFAULT; return; }
    var el = climbToLevel(pickBaseHit.el, pickLevel);
    if(el===document.body){
      pickHint.textContent = 'Selected: whole document / click to confirm';
    } else {
      pickHint.textContent = 'Selected: <'+el.tagName.toLowerCase()+'> / ↑ for parent, ↓ to go back, click to confirm';
    }
  }

  function pickTargetAt(e){
    var el = e.target;
    if(!el || el.nodeType!==1) return null;
    if(el.closest('#spBadge,#spSelectBtn,#spPopup,#spPanel,#spJsonModal,#spPickHint')) return null;
    if(el===document.body || el===document.documentElement) return null;
    if(isSvgEl(el)){
      // Inside a diagram: if data-sp-node is present, snap to it (a node is the semantic unit).
      // Otherwise fall back to picking the element itself. There's no concept of an insertion
      // point inside SVG, so `where` is always null.
      var dn = diagramNodeOf(el);
      return {el: dn || el, where:null};
    }
    var rect = el.getBoundingClientRect();
    if(e.clientY - rect.top <= EDGE) return {el:el, where:'before'};
    if(rect.bottom - e.clientY <= EDGE) return {el:el, where:'after'};
    return {el:el, where:null};
  }
  function renderPickVisual(hit){
    if(!hit){ pickOutline.style.display='none'; pickLine.style.display='none'; return; }
    var rect = hit.el.getBoundingClientRect();
    if(hit.where){
      pickOutline.style.display='none';
      pickLine.style.display='block';
      pickLine.style.left = rect.left+'px';
      pickLine.style.width = rect.width+'px';
      pickLine.style.top = (hit.where==='before' ? rect.top-2 : rect.bottom-1)+'px';
    } else {
      pickLine.style.display='none';
      pickOutline.style.display='block';
      pickOutline.style.left = rect.left+'px';
      pickOutline.style.top = rect.top+'px';
      pickOutline.style.width = rect.width+'px';
      pickOutline.style.height = rect.height+'px';
    }
  }
  function pickMouseMove(e){
    var hit = pickTargetAt(e);
    if(hit){
      if(!pickBaseHit || hit.el !== pickBaseHit.el) pickLevel = 0;
      pickBaseHit = hit;
    } else {
      pickBaseHit = null;
      pickLevel = 0;
    }
    renderPickVisual(effectiveHit());
    updatePickHintForLevel();
  }
  function pickClick(e){
    var hit = effectiveHit();
    if(!hit) return;
    e.preventDefault();
    e.stopPropagation();
    var target;
    if(hit.el===document.body){
      target = {kind:'document'};
    } else if(hit.el.hasAttribute && hit.el.hasAttribute('data-sp-node')){
      target = {
        kind: 'diagram-node',
        nodeId: hit.el.getAttribute('data-sp-node'),
        nodeLabel: hit.el.getAttribute('data-sp-label') || null,
        nearText: diagramNearText(hit.el)
      };
    } else if(hit.where){
      var prev = hit.where==='before' ? hit.el.previousElementSibling : hit.el;
      var next = hit.where==='before' ? hit.el : hit.el.nextElementSibling;
      target = {
        kind: 'insertion-point',
        afterPath: prev ? cssPath(prev) : null,
        beforePath: next ? cssPath(next) : null,
        afterTag: prev ? prev.tagName.toLowerCase() : null,
        beforeTag: next ? next.tagName.toLowerCase() : null,
        nearText: nearTextOf(prev || next)
      };
    } else {
      target = {
        kind: 'element',
        path: cssPath(hit.el),
        tag: hit.el.tagName.toLowerCase(),
        nearText: nearTextOf(hit.el)
      };
    }
    var cb = picking.onPick;
    var rect = hit.el.getBoundingClientRect();
    stopPickMode();
    cb(target, hit.el, rect);
  }
  function pickKeydown(e){
    if(e.key==='Escape'){
      e.preventDefault(); e.stopPropagation();
      var cancelCb = picking && picking.onCancel;
      stopPickMode();
      if(cancelCb) cancelCb();
      return;
    }
    if(e.key==='ArrowUp'){
      e.preventDefault(); e.stopPropagation();
      if(pickBaseHit){
        var cur = climbToLevel(pickBaseHit.el, pickLevel);
        if(cur !== document.body) pickLevel++;
      }
      renderPickVisual(effectiveHit());
      updatePickHintForLevel();
      return;
    }
    if(e.key==='ArrowDown'){
      e.preventDefault(); e.stopPropagation();
      if(pickLevel>0) pickLevel--;
      renderPickVisual(effectiveHit());
      updatePickHintForLevel();
      return;
    }
  }
  function startPickMode(onPick, onCancel){
    if(picking) stopPickMode();
    picking = {onPick:onPick, onCancel:onCancel};
    pickBaseHit = null;
    pickLevel = 0;
    clearTimeout(addTargetHintTimer);
    pickHint.textContent = PICK_HINT_DEFAULT;
    document.body.classList.add('sp-picking');
    pickHint.style.display='block';
    document.addEventListener('mousemove', pickMouseMove, true);
    document.addEventListener('click', pickClick, true);
    document.addEventListener('keydown', pickKeydown, true);
  }
  function stopPickMode(){
    picking = null;
    pickBaseHit = null;
    pickLevel = 0;
    document.body.classList.remove('sp-picking');
    pickHint.style.display='none';
    renderPickVisual(null);
    document.removeEventListener('mousemove', pickMouseMove, true);
    document.removeEventListener('click', pickClick, true);
    document.removeEventListener('keydown', pickKeydown, true);
  }

  function buildFlatMap(root){
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    var nodes = [], offsets = [], text = '', n;
    while((n = walker.nextNode())){
      offsets.push(text.length);
      nodes.push(n);
      text += n.nodeValue;
    }
    return {text:text, nodes:nodes, offsets:offsets};
  }
  function flatOffset(map, node, offset){
    var idx = map.nodes.indexOf(node);
    if(idx===-1) return -1;
    return map.offsets[idx] + offset;
  }

  // ---- persistence (localStorage only, host-agnostic key) ----
  function saveComments(list){
    try{ localStorage.setItem(STORAGE_KEY, JSON.stringify(list)); }catch(e){
      /* private mode etc. Keep working from in-memory state. */
    }
  }
  function loadComments(){
    try{
      var raw = localStorage.getItem(STORAGE_KEY);
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    }catch(e){ return []; }
  }

  // ---- data model v2: normalize into a targets[] array with a back-compat mirror ----
  function normalizeComment(c){
    if(!Array.isArray(c.targets) || c.targets.length===0){
      c.targets = [{
        label: '1',
        kind: 'text-range',
        selectedText: c.selectedText || '',
        contextBefore: c.contextBefore || '',
        contextAfter: c.contextAfter || ''
      }];
    }
    return c;
  }
  function firstTextRange(c){
    for(var i=0;i<c.targets.length;i++){
      if(c.targets[i].kind==='text-range') return c.targets[i];
    }
    return null;
  }

  // ---- questions (AI -> human. Answers are stored in localStorage `samepage-answers:{doc}`) ----
  function saveAnswers(list){
    try{ localStorage.setItem(ANSWERS_KEY, JSON.stringify(list)); }catch(e){}
  }
  function loadAnswers(){
    try{
      var raw = localStorage.getItem(ANSWERS_KEY);
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    }catch(e){ return []; }
  }
  var answers = [];
  function answerFor(qid){
    return answers.filter(function(a){ return a.questionId===qid; })[0] || null;
  }
  function setAnswer(qid, patch){
    var a = answerFor(qid);
    if(!a){ a = {questionId:qid, answer:null, note:''}; answers.push(a); }
    Object.keys(patch).forEach(function(k){ a[k]=patch[k]; });
    a.answeredAt = new Date().toISOString();
    saveAnswers(answers);
    refreshQuestionPins();
  }
  // Answered questions switch their pin from ❓ to ✓ (answer state comes from localStorage, so it
  // only persists within the same browser).
  function refreshQuestionPins(){
    var pins = document.querySelectorAll('.sp-qpin[data-sp-q-id],.sp-qpin-svg[data-sp-q-id]');
    Array.prototype.forEach.call(pins, function(p){
      var a = answerFor(p.getAttribute('data-sp-q-id'));
      var done = !!(a && a.answer);
      if(p.firstChild && p.firstChild.nodeType===3) p.firstChild.nodeValue = done ? '✓' : '❓';
      p.classList.toggle('sp-qpin-answered', done);
    });
  }
  // Pin anchor. Branches on the target's kind (element -> start of the element, text-range ->
  // right after the matched text, insertion-point -> at the position, no target -> no pin, panel only).
  function anchorQuestion(q){
    var t = q.target;
    if(!t) return false;
    var pin = document.createElement('span');
    pin.className = 'sp-qpin';
    pin.textContent = '❓';
    pin.setAttribute('data-sp-q-id', q.id);
    pin.title = q.question;
    pin.addEventListener('click', function(ev){
      ev.stopPropagation();
      panel.classList.add('open');
      highlightPanelItem(q.id);
    });
    if(t.kind==='diagram-node'){
      var nodeEl = resolveDiagramNode(t.nodeId, t.nodeLabel);
      if(!nodeEl) return false;
      return svgQuestionPin(nodeEl, q);
    }
    if(t.kind==='element'){
      var el = resolveByPath(t.path, t.tag, t.nearText);
      if(!el) return false;
      el.insertBefore(pin, el.firstChild);
      return true;
    }
    if(t.kind==='insertion-point'){
      var after = t.afterPath ? resolveByPath(t.afterPath, null, null) : null;
      var before = t.beforePath ? resolveByPath(t.beforePath, null, null) : null;
      if(after && after.parentNode){ after.parentNode.insertBefore(pin, after.nextSibling); return true; }
      if(before && before.parentNode){ before.parentNode.insertBefore(pin, before); return true; }
      return false;
    }
    // text-range: insert the pin right after the target text
    var root = (q.unit && unitElement(q.unit)) || document.body;
    var loc = locateText(root, t.selectedText, t.contextBefore, t.contextAfter);
    if(!loc) return false;
    // An HTML span pin can't be inserted into SVG text (it wouldn't render). Panel display only.
    if(insideSvg(loc.node)) return false;
    var afterNode = loc.node.splitText(loc.start + loc.len);
    afterNode.parentNode.insertBefore(pin, afterNode);
    return true;
  }
  // A question pin planted on a node inside an SVG diagram. Drawn as SVG text at the node's
  // bounding box, top-right corner.
  function svgQuestionPin(el, q){
    var box;
    try{ box = el.getBBox(); }catch(e){ return false; }
    var pin = document.createElementNS(SVG_NS, 'text');
    pin.textContent = '❓';
    pin.setAttribute('x', box.x + box.width - 6);
    pin.setAttribute('y', box.y + 4);
    pin.setAttribute('font-size', '16');
    pin.setAttribute('class', 'sp-qpin-svg');
    pin.setAttribute('data-sp-q-id', q.id);
    var title = document.createElementNS(SVG_NS, 'title');
    title.textContent = q.question;
    pin.appendChild(title);
    pin.addEventListener('click', function(ev){
      ev.stopPropagation();
      panel.classList.add('open');
      highlightPanelItem(q.id);
    });
    appendSvgOverlay(el, pin);
    return true;
  }
  function renderQuestions(){
    panelQuestions.innerHTML = '';
    QUESTIONS.forEach(function(q){
      var item = document.createElement('div');
      item.className = 'sp-qitem';
      item.dataset.spCmtId = q.id;   // reuses highlightPanelItem
      var qDiv = document.createElement('div');
      qDiv.className = 'sp-qitem-q';
      qDiv.textContent = q.question;
      item.appendChild(qDiv);
      var current = answerFor(q.id);
      if(q.choices && q.choices.length){
        var row = document.createElement('div');
        row.className = 'sp-qitem-choices';
        q.choices.forEach(function(choice){
          var b = document.createElement('button');
          b.type = 'button';
          b.textContent = choice;
          if(current && current.answer===choice) b.classList.add('selected');
          b.addEventListener('click', function(e){
            e.stopPropagation();
            setAnswer(q.id, {answer: choice});
            renderQuestions();
            renderBadge();
          });
          row.appendChild(b);
        });
        item.appendChild(row);
      }
      var ta = document.createElement('textarea');
      ta.placeholder = q.choices && q.choices.length ? 'Add a note (optional)' : 'Enter your answer';
      ta.value = current ? (current.note || '') : '';
      ta.addEventListener('click', function(e){ e.stopPropagation(); });
      ta.addEventListener('change', function(){
        setAnswer(q.id, q.choices && q.choices.length ? {note: ta.value} : {answer: ta.value});
        renderBadge();
      });
      item.appendChild(ta);
      if(current && current.answer){
        var done = document.createElement('div');
        done.className = 'sp-qitem-answered';
        done.textContent = '✓ Answered';
        item.appendChild(done);
      }
      item.addEventListener('click', function(){
        var pin = document.querySelector('.sp-qpin[data-sp-q-id="'+cssEsc(q.id)+'"],.sp-qpin-svg[data-sp-q-id="'+cssEsc(q.id)+'"]');
        if(pin) pin.scrollIntoView({behavior:'smooth', block:'center'});
      });
      panelQuestions.appendChild(item);
    });
  }

  function init(){
    comments = loadComments().map(normalizeComment);
    comments.forEach(function(c){
      c.targets.forEach(function(t){ t.anchored = anchorTarget(c, t); });
    });
    RESPONSES.forEach(function(r){ r.anchored = anchorResponse(r); });
    // The text-range anchor for question pins mutates the DOM via splitText, so it must run
    // after comments/responses are anchored (to avoid shifting the flat-map offsets).
    answers = loadAnswers();
    QUESTIONS.forEach(function(q){ q.anchored = anchorQuestion(q); });
    refreshQuestionPins();
    renderQuestions();
    renderPanel();
  }

  // ---- anchoring / highlighting ----
  // Locates the target within the visible text under root and returns the text node plus an
  // in-node offset. Returns null if not found.
  function locateText(root, target, contextBefore, contextAfter){
    if(!root || !target) return null;
    var map = buildFlatMap(root);
    var text = map.text;
    var occ = [], from = 0, p;
    while((p = text.indexOf(target, from)) !== -1){ occ.push(p); from = p+1; }
    if(occ.length===0) return null;
    var chosen;
    if(occ.length===1){
      chosen = occ[0];
    } else {
      var scored = occ.map(function(o){
        var before = text.slice(Math.max(0,o-40), o);
        var after = text.slice(o+target.length, o+target.length+40);
        var score = 0;
        if(contextBefore && before.indexOf(contextBefore.slice(-20)) >= 0) score++;
        if(contextAfter && after.indexOf(contextAfter.slice(0,20)) >= 0) score++;
        return {o:o, score:score};
      });
      scored.sort(function(a,b){ return b.score-a.score; });
      chosen = scored[0].o;
    }
    var nodeIdx = -1;
    for(var i=0;i<map.offsets.length;i++){
      var start = map.offsets[i], len = map.nodes[i].nodeValue.length;
      if(chosen>=start && chosen<start+len){ nodeIdx = i; break; }
    }
    if(nodeIdx===-1) return null;
    var node = map.nodes[nodeIdx];
    var localStart = chosen - map.offsets[nodeIdx];
    var maxLen = node.nodeValue.length - localStart;
    var markLen = Math.min(target.length, maxLen);
    if(markLen<=0) return null;
    return {node:node, start:localStart, len:markLen};
  }
  // Wraps `mark` around loc's position; clicking it opens the matching panel item.
  function wrapMark(loc, mark, panelItemId){
    try{
      var range = document.createRange();
      range.setStart(loc.node, loc.start);
      range.setEnd(loc.node, loc.start+loc.len);
      try{
        range.surroundContents(mark);
        mark.addEventListener('click', function(ev){
          ev.stopPropagation();
          panel.classList.add('open');
          highlightPanelItem(panelItemId);
        });
      }catch(e){ /* the range straddles an element boundary etc. The location was still found, so
                    treat it as anchored but skip the visual highlight. */ }
      return true;
    }catch(e){ return false; }
  }
  function anchorTarget(c, t){
    if(t.kind==='element') return anchorElementTarget(c, t);
    if(t.kind==='insertion-point') return anchorInsertionTarget(c, t);
    if(t.kind==='diagram-node') return anchorDiagramTarget(c, t);
    if(t.kind==='document') return true;   // whole document: no mark added to the body
    return anchorTextTarget(c, t);   // formerly the body of anchorComment
  }
  function anchorDiagramTarget(c, t){
    var el = resolveDiagramNode(t.nodeId, t.nodeLabel);
    if(!el) return false;
    if(!svgHalo(el, c.id, c.status==='resolved')) return false;
    el.addEventListener('click', function(ev){
      if(picking) return;
      ev.stopPropagation();
      panel.classList.add('open');
      highlightPanelItem(c.id);
    });
    return true;
  }
  function anchorElementTarget(c, t){
    var el = resolveByPath(t.path, t.tag, t.nearText);
    if(!el) return false;
    el.classList.add('sp-mark-el');
    el.setAttribute('data-sp-cmt-id', c.id);
    if(c.targets.length>1) el.setAttribute('data-sp-badge', t.label);
    el.addEventListener('click', function(ev){
      if(picking) return;
      ev.stopPropagation();
      panel.classList.add('open');
      highlightPanelItem(c.id);
    });
    return true;
  }
  function anchorInsertionTarget(c, t){
    var after = t.afterPath ? resolveByPath(t.afterPath, t.afterTag, t.nearText) : null;
    var before = (!after && t.beforePath) ? resolveByPath(t.beforePath, t.beforeTag, t.nearText) : null;
    if(!after && !before) return false;
    var markEl = document.createElement('span');
    markEl.className = 'sp-insert-mark';
    markEl.setAttribute('data-sp-cmt-id', c.id);
    if(c.targets.length>1) markEl.setAttribute('data-sp-badge', t.label);
    if(after && after.parentNode){
      after.parentNode.insertBefore(markEl, after.nextSibling);
    } else {
      before.parentNode.insertBefore(markEl, before);
    }
    markEl.addEventListener('click', function(ev){
      ev.stopPropagation();
      panel.classList.add('open');
      highlightPanelItem(c.id);
    });
    return true;
  }
  function anchorTextTarget(c, t){
    // With multiple targets, the 2nd+ target may belong to a different unit than the first, so
    // prefer the target's own unit (if set) when resolving root.
    var root = unitElement(t.unit || c.unit);
    if(!root) return false;
    var loc = locateText(root, t.selectedText, t.contextBefore, t.contextAfter);
    if(!loc) return false;
    // An HTML <mark> can't be wrapped around SVG text (it would break the rendering). The
    // location was found, so treat it as anchored but skip the highlight.
    if(insideSvg(loc.node)) return true;
    var mark = document.createElement('mark');
    mark.className = 'sp-mark' + (c.status==='resolved' ? ' sp-mark-resolved' : '');
    mark.dataset.spCmtId = c.id;
    if(c.targets.length>1) mark.dataset.spBadge = t.label;
    mark.title = c.comment;
    return wrapMark(loc, mark, c.id);
  }
  // Fixes a response's fixedText (post-fix text) in the body and marks it green.
  function anchorResponse(r){
    if(!r.fixedText) return false;
    var root = (r.unit && unitElement(r.unit)) || document.body;
    var loc = locateText(root, r.fixedText, r.contextBefore, r.contextAfter);
    if(!loc) return false;
    if(insideSvg(loc.node)) return true;   // skip highlight inside SVG, same reasoning as text-range
    var mark = document.createElement('mark');
    mark.className = 'sp-mark-fixed';
    mark.dataset.spRespId = r.id;
    mark.title = r.reply;
    return wrapMark(loc, mark, r.id);
  }
  function updateMarkResolvedState(c){
    document.querySelectorAll('mark.sp-mark[data-sp-cmt-id="'+cssEsc(c.id)+'"]').forEach(function(m){
      m.classList.toggle('sp-mark-resolved', c.status==='resolved');
    });
    document.querySelectorAll('.sp-node-halo[data-sp-cmt-id="'+cssEsc(c.id)+'"]').forEach(function(h){
      h.classList.toggle('sp-node-halo-resolved', c.status==='resolved');
    });
  }
  function removeMarksFor(id){
    document.querySelectorAll('mark.sp-mark[data-sp-cmt-id="'+cssEsc(id)+'"]').forEach(function(m){
      var parent = m.parentNode;
      parent.replaceChild(document.createTextNode(m.textContent), m);
      if(parent.normalize) parent.normalize();
    });
    document.querySelectorAll('.sp-mark-el[data-sp-cmt-id="'+cssEsc(id)+'"]').forEach(function(el){
      el.classList.remove('sp-mark-el');
      el.removeAttribute('data-sp-cmt-id');
      el.removeAttribute('data-sp-badge');
    });
    document.querySelectorAll('.sp-insert-mark[data-sp-cmt-id="'+cssEsc(id)+'"]').forEach(function(el){
      el.parentNode.removeChild(el);
    });
    document.querySelectorAll('.sp-node-halo[data-sp-cmt-id="'+cssEsc(id)+'"]').forEach(function(el){
      el.parentNode.removeChild(el);
    });
  }

  // ---- responses (embedded in the HTML; not dependent on localStorage) ----
  function responseFor(id){
    return RESPONSES.filter(function(r){ return r.id===id; })[0] || null;
  }
  function actionLabel(action){
    if(action==='partial') return 'Partially fixed';
    if(action==='declined') return 'Declined';
    if(action==='noted') return 'Acknowledged';
    return 'Fixed';
  }
  function jumpToFixed(r){
    var mark = document.querySelector('mark.sp-mark-fixed[data-sp-resp-id="'+cssEsc(r.id)+'"]');
    if(mark){
      mark.scrollIntoView({behavior:'smooth', block:'center'});
    } else {
      jumpToUnit(r.unit);
    }
  }
  function buildResponseBlock(r){
    var div = document.createElement('div');
    div.className = 'sp-response';
    var head = document.createElement('div');
    head.className = 'sp-response-head';
    var icon = document.createElement('span');
    icon.textContent = '🤖 ';
    head.appendChild(icon);
    var actionBadge = document.createElement('span');
    actionBadge.className = 'sp-response-action sp-action-' + (r.action || 'fixed');
    actionBadge.textContent = actionLabel(r.action);
    head.appendChild(actionBadge);
    div.appendChild(head);
    var reply = document.createElement('div');
    reply.className = 'sp-response-reply';
    reply.textContent = r.reply;
    div.appendChild(reply);
    div.addEventListener('click', function(e){
      e.stopPropagation();
      jumpToFixed(r);
    });
    return div;
  }

  // ---- panel ----
  function renderBadge(){
    badge.textContent = '💬 ' + comments.length + (QUESTIONS.length ? ' ❓' + QUESTIONS.filter(function(q){ var a=answerFor(q.id); return !(a&&a.answer); }).length : '');
  }
  function renderPanel(){
    panelCount.textContent = comments.length;
    panelList.innerHTML = '';
    var sorted = comments.slice().sort(function(a,b){
      var elA = unitElement(a.unit), elB = unitElement(b.unit);
      if(elA && elB && elA !== elB){
        return (elA.compareDocumentPosition(elB) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1;
      }
      return 0;
    });
    sorted.forEach(function(c){
      var item = document.createElement('div');
      item.className = 'sp-item' + (c.status==='resolved' ? ' resolved' : '');
      item.dataset.spCmtId = c.id;

      var unitDiv = document.createElement('div');
      unitDiv.className = 'sp-item-unit';
      unitDiv.textContent = c.unitLabel || c.unit || '';
      if(c.action && ACTION_LABEL[c.action]){
        var actionSpan = document.createElement('span');
        actionSpan.className = 'sp-item-action';
        actionSpan.textContent = '['+ACTION_LABEL[c.action]+']';
        unitDiv.appendChild(actionSpan);
      }
      item.appendChild(unitDiv);

      if(c.targets.some(function(t){ return t.anchored===false; })){
        var na = document.createElement('div');
        na.className = 'sp-item-noanchor';
        na.textContent = '⚠ Original text not found';
        item.appendChild(na);
      }

      var excerptDiv = document.createElement('div');
      excerptDiv.className = 'sp-item-excerpt';
      excerptDiv.textContent = c.targets.map(function(t){
        var head = c.targets.length>1 ? '①②③④⑤⑥⑦⑧⑨'.charAt((+t.label)-1)+' ' : '';
        if(t.kind==='diagram-node') return head + '[diagram] ' + truncate(t.nodeLabel||t.nearText||t.nodeId, 24);
        if(t.kind==='element') return head + '[element] ' + truncate(t.nearText||t.tag, 24);
        if(t.kind==='insertion-point') return head + '[position] near ' + truncate(t.nearText||'', 24);
        if(t.kind==='document') return head + '[whole doc]';
        return head + '"' + truncate(t.selectedText, 24) + '"';
      }).join(' / ');
      item.appendChild(excerptDiv);

      if(c.id === editingId){
        var editTa = document.createElement('textarea');
        editTa.className = 'sp-edit-textarea';
        editTa.value = c.comment;
        editTa.dataset.spCmtId = c.id;
        editTa.addEventListener('click', function(e){ e.stopPropagation(); });
        item.appendChild(editTa);

        var editActions = document.createElement('div');
        editActions.className = 'sp-item-actions';
        var cancelEditBtn = document.createElement('button');
        cancelEditBtn.type = 'button';
        cancelEditBtn.textContent = 'Cancel';
        cancelEditBtn.addEventListener('click', function(e){
          e.stopPropagation();
          editingId = null;
          renderPanel();
        });
        var saveEditBtn = document.createElement('button');
        saveEditBtn.type = 'button';
        saveEditBtn.textContent = 'Save';
        saveEditBtn.addEventListener('click', function(e){
          e.stopPropagation();
          commitEdit(c, editTa);
        });
        editActions.appendChild(cancelEditBtn);
        editActions.appendChild(saveEditBtn);
        item.appendChild(editActions);
      } else {
        var commentDiv = document.createElement('div');
        commentDiv.className = 'sp-item-comment';
        commentDiv.textContent = c.comment;
        item.appendChild(commentDiv);

        var actions = document.createElement('div');
        actions.className = 'sp-item-actions';
        var editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.textContent = 'Edit';
        editBtn.addEventListener('click', function(e){
          e.stopPropagation();
          editingId = c.id;
          renderPanel();
          focusEditTextarea();
        });
        var resolveBtn = document.createElement('button');
        resolveBtn.type = 'button';
        resolveBtn.textContent = c.status==='resolved' ? 'Reopen' : 'Resolve';
        resolveBtn.addEventListener('click', function(e){
          e.stopPropagation();
          c.status = c.status==='resolved' ? 'open' : 'resolved';
          updateMarkResolvedState(c);
          saveComments(comments);
          renderPanel();
        });
        var delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.textContent = 'Delete';
        delBtn.addEventListener('click', function(e){
          e.stopPropagation();
          removeMarksFor(c.id);
          comments = comments.filter(function(x){ return x.id!==c.id; });
          saveComments(comments);
          renderPanel();
        });
        actions.appendChild(editBtn);
        actions.appendChild(resolveBtn);
        actions.appendChild(delBtn);
        item.appendChild(actions);
      }

      var resp = responseFor(c.id);
      if(resp){
        item.appendChild(buildResponseBlock(resp));
      }

      item.addEventListener('click', function(){
        if(c.id === editingId) return;
        if(c.unit){
          jumpToUnit(c.unit);
        } else if(c.targets[0] && c.targets[0].kind==='document'){
          window.scrollTo({top:0, behavior:'smooth'});
        } else {
          var anchorEl = document.querySelector('[data-sp-cmt-id="'+cssEsc(c.id)+'"]');
          if(anchorEl) anchorEl.scrollIntoView({behavior:'smooth', block:'center'});
        }
      });
      panelList.appendChild(item);
    });
    // A response with no matching comment in localStorage (e.g. opened in a different browser)
    // is shown as its own item at the end of the list.
    var known = {};
    comments.forEach(function(c){ known[c.id] = true; });
    RESPONSES.forEach(function(r){
      if(known[r.id]) return;
      var item = document.createElement('div');
      item.className = 'sp-item sp-item-response-only';
      item.dataset.spCmtId = r.id;
      var unitDiv = document.createElement('div');
      unitDiv.className = 'sp-item-unit';
      unitDiv.textContent = '(no source comment)';
      item.appendChild(unitDiv);
      item.appendChild(buildResponseBlock(r));
      item.addEventListener('click', function(){ jumpToFixed(r); });
      panelList.appendChild(item);
    });
    renderBadge();
  }
  function focusEditTextarea(){
    var ta = panelList.querySelector('.sp-edit-textarea');
    if(!ta) return;
    ta.focus();
    var len = ta.value.length;
    try{ ta.setSelectionRange(len, len); }catch(e){ /* unsupported in some browsers */ }
  }
  function commitEdit(c, textarea){
    var val = textarea.value.trim();
    if(!val) return;
    c.comment = val;
    document.querySelectorAll('mark.sp-mark[data-sp-cmt-id="'+cssEsc(c.id)+'"]').forEach(function(m){
      m.title = c.comment;
    });
    saveComments(comments);
    editingId = null;
    renderPanel();
  }
  function highlightPanelItem(id){
    // Includes panelQuestions (question list), not just panelList (comment list). Question items
    // live in panelQuestions, a sibling of panelList, so panelList.querySelector alone won't find them.
    var el = panel.querySelector('[data-sp-cmt-id="'+cssEsc(id)+'"]');
    if(el){
      el.scrollIntoView({block:'center'});
      el.style.outline = '2px solid var(--sp-accent, #0f766e)';
      setTimeout(function(){ el.style.outline=''; }, 1500);
    }
  }

  // ---- select-to-comment flow ----
  function hideSelectBtn(){ selectBtn.style.display = 'none'; }
  function showSelectBtn(range){
    var rect = range.getBoundingClientRect();
    selectBtn.style.left = Math.min(window.innerWidth-140, Math.max(4, rect.right)) + 'px';
    selectBtn.style.top = Math.max(4, rect.top-36) + 'px';
    selectBtn.style.display = 'block';
  }

  // ---- verb palette (move / insert / delete / shorten / keep) ----
  function setAction(action){
    pendingAction = (pendingAction===action) ? null : action;   // clicking again clears it
    Array.prototype.forEach.call(popupPalette.querySelectorAll('button'), function(b){
      b.classList.toggle('active', b.getAttribute('data-sp-action')===pendingAction);
    });
    updateGuide();
  }
  function updateGuide(){
    var g = '';
    if(pendingAction==='move'){
      if(pendingTargets.length<1) g = '① Select what to move (text selection or e key)';
      else if(pendingTargets.length<2) g = '② Select the destination (press e, then click near an element’s top/bottom edge)';
      else g = 'Moving ① to ②. Add a note if needed';
    } else if(pendingAction==='insert'){
      g = pendingTargets.length<1 ? 'Select the insertion point (press e, then click near an element’s edge)' : 'Enter what to insert';
    } else if(pendingAction){
      g = ACTION_LABEL[pendingAction] + ': select a target and save';
    }
    popupGuide.textContent = g;
  }
  Array.prototype.forEach.call(popupPalette.querySelectorAll('button'), function(b){
    b.addEventListener('click', function(){ setAction(b.getAttribute('data-sp-action')); });
  });

  // ---- pendingTargets (multiple targets) and chip display ----
  function addPendingTarget(unit, unitLabel, target){
    target.label = String(pendingTargets.length + 1);
    pendingTargets.push({unit:unit, unitLabel:unitLabel, target:target});
    renderChips();
    updateGuide();
  }
  function chipText(t){
    var mark = '①②③④⑤⑥⑦⑧⑨'.charAt((+t.label)-1) || t.label;
    if(t.kind==='diagram-node') return mark+' [diagram] '+truncate(t.nodeLabel||t.nearText||t.nodeId,20);
    if(t.kind==='element') return mark+' [element] '+truncate(t.nearText||t.tag,20);
    if(t.kind==='insertion-point') return mark+' [position] near '+truncate(t.nearText||'',20);
    if(t.kind==='document') return mark+' 📄 whole document';
    return mark+' "'+truncate(t.selectedText,20)+'"';
  }
  function renderChips(){
    popupChips.innerHTML = '';
    pendingTargets.forEach(function(pt){
      var chip = document.createElement('span');
      chip.className = 'sp-chip';
      chip.textContent = chipText(pt.target);
      popupChips.appendChild(chip);
    });
  }

  function closePopup(){
    popup.style.display = 'none';
    popup.style.visibility = '';
    hideSelectBtn();
    popupText.value = '';
    pendingSelection = null;
    pendingTargets = [];
    renderChips();
    pendingAction = null;
    Array.prototype.forEach.call(popupPalette.querySelectorAll('button'), function(b){
      b.classList.remove('active');
    });
    updateGuide();
    popupOpen = false;
    window.getSelection().removeAllRanges();
  }
  function showPopup(anchorRect){
    var rect = anchorRect || selectBtn.getBoundingClientRect();
    popup.style.left = Math.min(window.innerWidth-300, Math.max(4, rect.left)) + 'px';
    popup.style.top = Math.min(window.innerHeight-160, Math.max(4, rect.bottom+6)) + 'px';
    popup.style.display = 'block';
    popup.style.visibility = '';
    popupOpen = true;
    hideSelectBtn();
    popupText.value = '';
    popupText.focus();
  }

  document.addEventListener('mouseup', function(e){
    if(e.target.closest && e.target.closest('#spSelectBtn,#spPopup,#spPanel,#spBadge,#spJsonModal')) return;
    setTimeout(function(){
      var sel = window.getSelection();
      var text = sel && sel.toString();
      if(!text || !text.trim() || sel.rangeCount===0){ if(!popupOpen) hideSelectBtn(); return; }
      var range = sel.getRangeAt(0);
      var container = range.startContainer.nodeType===1 ? range.startContainer : range.startContainer.parentElement;
      var info = unitInfoFor(container);
      if(!info){ if(!popupOpen) hideSelectBtn(); return; }
      var map = buildFlatMap(info.el);
      var startFlat = flatOffset(map, range.startContainer, range.startOffset);
      var endFlat = flatOffset(map, range.endContainer, range.endOffset);
      var contextBefore = '', contextAfter = '';
      if(startFlat>=0 && endFlat>=0){
        contextBefore = map.text.slice(Math.max(0,startFlat-40), startFlat);
        contextAfter = map.text.slice(endFlat, endFlat+40);
      }
      if(popupOpen){
        // a text selection made while the popup is open is added directly as a target,
        // skipping the selectBtn step
        addPendingTarget(info.unit, info.unitLabel, {
          kind:'text-range', selectedText:text, contextBefore:contextBefore, contextAfter:contextAfter
        });
        window.getSelection().removeAllRanges();
        return;
      }
      pendingSelection = {unit:info.unit, unitLabel:info.unitLabel, selectedText:text, contextBefore:contextBefore, contextAfter:contextAfter};
      showSelectBtn(range);
    }, 0);
  });

  selectBtn.addEventListener('mousedown', function(e){ e.preventDefault(); });
  selectBtn.addEventListener('click', function(e){
    e.preventDefault();
    if(!pendingSelection) return;
    var ps = pendingSelection;
    pendingSelection = null;
    addPendingTarget(ps.unit, ps.unitLabel, {
      kind:'text-range', selectedText:ps.selectedText, contextBefore:ps.contextBefore, contextAfter:ps.contextAfter
    });
    showPopup();
  });
  popupAddTarget.addEventListener('click', function(){
    // 'e' can't be typed while the textarea has focus, so blur it and show a temporary hint
    // ("select body text, or press e to pick an element").
    popupText.blur();
    clearTimeout(addTargetHintTimer);
    pickHint.textContent = 'Select text in the body, or press e to pick an element';
    pickHint.style.display = 'block';
    addTargetHintTimer = setTimeout(function(){
      pickHint.style.display = 'none';
      pickHint.textContent = PICK_HINT_DEFAULT;
    }, 2200);
  });
  popupSave.addEventListener('click', function(){
    var val = popupText.value.trim();
    if(!val && !pendingAction){ closePopup(); return; }
    if(pendingAction && pendingTargets.length===0){
      popupGuide.textContent = 'Select a target (text selection or e key)';
      return;   // keep it open, waiting for a selection
    }
    if(pendingAction==='move' && pendingTargets.length<2){
      popupGuide.textContent = '② Select the destination';
      return;   // keep it open, waiting for the destination
    }
    if(pendingTargets.length===0){ closePopup(); return; }
    if(!val){
      var marks = '①②③④⑤⑥⑦⑧⑨';
      if(pendingAction==='move' && pendingTargets.length>=2) val = '[Move] '+marks[0]+' to '+marks[1];
      else val = '['+ACTION_LABEL[pendingAction]+']';
    }
    if(pendingAction==='move' && pendingTargets.length>=2){
      pendingTargets[0].target.role = 'source';
      pendingTargets[1].target.role = 'destination';
    }
    var c = {
      id: 'c-' + randomId8(),
      unit: pendingTargets[0].unit,
      unitLabel: pendingTargets[0].unitLabel,
      targets: pendingTargets.map(function(pt){
        // A text-range target can only be located within the unit it belongs to, so store the
        // target's own unit on itself in case a non-first target belongs to a different unit.
        if(pt.target.kind==='text-range') pt.target.unit = pt.unit;
        return pt.target;
      }),
      action: pendingAction || undefined,
      comment: val,
      status: 'open',
      createdAt: new Date().toISOString()
    };
    comments.push(c);
    c.targets.forEach(function(t){ t.anchored = anchorTarget(c, t); });
    saveComments(comments);
    renderPanel();
    closePopup();
  });
  popupCancel.addEventListener('click', function(){ closePopup(); });

  badge.addEventListener('click', function(){ panel.classList.toggle('open'); });
  panelClose.addEventListener('click', function(){ panel.classList.remove('open'); });

  // ---- JSON view / copy modal ----
  function isJsonModalOpen(){ return jsonModal.classList.contains('open'); }
  // Even if the JSON alone is pasted into a fresh session, work should still be able to proceed,
  // so a self-describing header goes on top. _howto invokes the skill, _rules prevents
  // misreading even where the skill isn't installed, and sourceHtml identifies the target file
  // (all three together make it self-contained).
  var HANDOFF_HOWTO =
    'This is human review feedback exported by samepage. Treat it as a work order for applying ' +
    'changes. If the "samepage" skill is available in this environment, invoke it and follow ' +
    'SKILL.md’s sections on the JSON contract and on replying to comments. If it is not ' +
    'available, proceed using _rules alone.';
  var HANDOFF_RULES = [
    'Fix the original source, not this HTML. If sourceHtml was generated from another source ' +
      '(e.g. Markdown), edit that source instead — direct edits to the HTML are lost on the ' +
      'next regeneration.',
    'Locate the target using selectedText. If it matches more than once, disambiguate using the ' +
      'end of contextBefore and the start of contextAfter.',
    'Markup syntax (e.g. Markdown **bold**, links) is stripped when rendering to HTML, so ' +
      'selectedText may not appear verbatim in the original source. Search again with the ' +
      'formatting removed.',
    'anchored:false means the original text could not be found. Don’t discard it — infer ' +
      'the intended fix from unitLabel / comment / targets[].nearText, apply it, and clearly state ' +
      'that it was inferred.',
    'Do not modify comments with status:"resolved".',
    'If action (move/insert/delete/shorten/keep) has a value, it is authoritative even if the ' +
      'comment text reads like a template. action:"keep" is an explicit approval — never undo it.',
    'When targets has 2+ entries with a role, move the content of the role:"source" target to the ' +
      'position of the role:"destination" target.',
    'targets[].kind has five forms: text-range = search body text; element = a path ' +
      '(nth-of-type chain), falling back to tag + nearText if broken; insertion-point = the ' +
      'position right after the element at afterPath (beforePath is for cross-checking / ' +
      'fallback); diagram-node = a node inside an SVG diagram, where nodeId is the same stable id ' +
      'as data-sp-node in the original source (the IR / diagram definition that generated the ' +
      'SVG) — fix that source, not the HTML; document = a whole-document remark with no ' +
      'specific location, to be treated as a structural/tone/policy-level instruction.',
    'The top-level selectedText / contextBefore / contextAfter / anchored fields are a duplicate ' +
      'of the comment’s first text-range target (kept for backward compatibility). They are ' +
      'null for comments with no text-range target.',
    'answers holds the human’s responses to question pins (❓) in the body. Match them by ' +
      'questionId and treat them as additional instructions. Once fixes are applied, build a ' +
      'responses JSON (id / reply / action / fixedText) and inject it back via samepage’s ' +
      '--responses flag so it reaches sourceHtml. Reply to every comment, even ones left ' +
      'unchanged, using action:"declined" or "noted".'
  ];
  function buildJson(){
    return JSON.stringify({
      _howto: HANDOFF_HOWTO,
      _skill: 'samepage',
      _rules: HANDOFF_RULES,
      doc: DOC_ID,
      sourceHtml: CFG.sourcePath || null,
      generatedAt: new Date().toISOString(),
      answers: answers.filter(function(a){ return a.answer || a.note; }),
      comments: comments.map(function(c){
        var tr = firstTextRange(c);
        return {
          id: c.id,
          unit: c.unit,
          unitLabel: c.unitLabel,
          targets: c.targets.map(function(t){
            var o = {label:t.label, kind:t.kind, anchored:t.anchored!==false};
            if(t.role) o.role = t.role;
            if(t.kind==='text-range'){
              o.selectedText=t.selectedText; o.contextBefore=t.contextBefore; o.contextAfter=t.contextAfter;
            } else if(t.kind==='diagram-node'){
              o.nodeId=t.nodeId; o.nodeLabel=t.nodeLabel||null; o.nearText=t.nearText||null;
            } else if(t.kind==='element'){
              o.path=t.path; o.tag=t.tag; o.nearText=t.nearText;
            } else if(t.kind==='insertion-point'){
              o.afterPath=t.afterPath; o.beforePath=t.beforePath; o.nearText=t.nearText;
              o.afterTag=t.afterTag; o.beforeTag=t.beforeTag;
            }
            return o;
          }),
          action: c.action || null,
          comment: c.comment,
          status: c.status,
          anchored: tr ? tr.anchored !== false : (c.targets[0].anchored !== false),
          selectedText: tr ? tr.selectedText : null,
          contextBefore: tr ? tr.contextBefore : null,
          contextAfter: tr ? tr.contextAfter : null,
          createdAt: c.createdAt
        };
      })
    }, null, 2);
  }
  function openJsonModal(){
    var hasAnswers = answers.some(function(a){ return a.answer || a.note; });
    if(comments.length===0 && !hasAnswers){
      jsonText.value = 'No comments yet';
    } else {
      jsonText.value = buildJson();
    }
    jsonModal.classList.add('open');
    jsonCopyBtn.textContent = 'Copy';
  }
  function closeJsonModal(){
    jsonModal.classList.remove('open');
  }
  jsonBtn.addEventListener('click', openJsonModal);
  jsonCloseBtn.addEventListener('click', closeJsonModal);
  jsonOverlay.addEventListener('click', closeJsonModal);
  // Shared by the modal's Copy button, the panel's Copy JSON button and the 'j' shortcut.
  // The execCommand fallback copies from a throwaway off-screen textarea rather than #spJsonText:
  // the direct-copy paths run with the modal closed, and a display:none textarea can't be selected.
  function copyJsonToClipboard(text, onDone){
    function fallbackCopy(){
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;top:0;left:-9999px;opacity:0;';
      document.body.appendChild(ta);
      ta.select();
      try{ document.execCommand('copy'); }catch(e){}
      document.body.removeChild(ta);
      if(onDone) onDone();
    }
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(text).then(function(){ if(onDone) onDone(); }).catch(fallbackCopy);
    } else {
      fallbackCopy();
    }
  }
  jsonCopyBtn.addEventListener('click', function(){
    copyJsonToClipboard(jsonText.value, function(){
      jsonCopyBtn.textContent = '✓ Copied';
      setTimeout(function(){ jsonCopyBtn.textContent = 'Copy'; }, 1500);
    });
  });
  // Copy the export JSON straight to the clipboard, without requiring the modal to be opened
  // first. Shared by the panel's Copy JSON button and the 'j' shortcut. copied===false means
  // there was nothing to copy yet.
  function copyJsonDirect(onDone){
    var hasAnswers = answers.some(function(a){ return a.answer || a.note; });
    if(comments.length===0 && !hasAnswers){
      if(onDone) onDone(false);
      return;
    }
    copyJsonToClipboard(buildJson(), function(){
      if(onDone) onDone(true);
    });
  }
  var JSON_COPY_DIRECT_LABEL = jsonCopyDirectBtn.textContent;
  var JSON_COPY_FLASH_MS = 1500;
  var jsonCopyFlashTimer = null;
  // Flash the result on both the badge and the panel's Copy JSON button, whichever route the copy
  // came from: the open panel covers the badge, so a badge-only flash is invisible exactly when the
  // panel is in use, and a button-only flash is invisible when the panel is closed.
  function flashJsonCopied(copied){
    jsonCopyDirectBtn.textContent = copied ? '✓ Copied' : 'No comments yet';
    if(copied) badge.textContent = '✓ Copied';
    clearTimeout(jsonCopyFlashTimer);   // a second copy restarts the flash instead of cutting it short
    jsonCopyFlashTimer = setTimeout(function(){
      jsonCopyDirectBtn.textContent = JSON_COPY_DIRECT_LABEL;
      renderBadge();
    }, JSON_COPY_FLASH_MS);
  }
  // 'j' keyboard shortcut.
  function copyJsonShortcut(){
    copyJsonDirect(flashJsonCopied);
  }
  jsonCopyDirectBtn.addEventListener('click', function(){
    copyJsonDirect(flashJsonCopied);
  });

  // ---- whole-document comment (a remark that doesn't point at a specific spot) ----
  docCommentBtn.addEventListener('click', function(){
    var already = pendingTargets.some(function(pt){ return pt.target.kind==='document'; });
    if(already){
      popupGuide.textContent = 'A whole-document comment is already added';
      setTimeout(updateGuide, 1500);
      return;
    }
    addPendingTarget(null, 'Whole document', {kind:'document'});
    if(!popupOpen){
      var panelRect = panel.getBoundingClientRect();
      showPopup({left: Math.max(4, panelRect.left - 296), bottom: 60});
    }
  });

  // A click while there's an active text selection should not propagate to the host page's own
  // click handlers (e.g. advancing slides). Prevents a misfire right after selecting text.
  document.addEventListener('click', function(e){
    if(picking) return;
    if(e.target.closest && e.target.closest('#spSelectBtn,#spPopup,#spPanel,#spBadge,#spJsonModal')) return;
    var sel = window.getSelection();
    if(sel && sel.toString().length>0){
      e.stopPropagation();
    }
  }, true);

  // Enter confirms / Shift+Enter adds a newline / Escape cancels, for the new-comment textarea.
  function handlePopupTextareaKey(e){
    if(isImeComposing(e)) return;   // leave IME composition/cancellation keys to the IME
    if(e.key==='Escape'){
      e.preventDefault();
      closePopup();
      return;
    }
    if(e.key==='Enter' && !e.shiftKey){
      e.preventDefault();
      popupSave.click();
    }
  }
  // Enter confirms / Shift+Enter adds a newline / Escape cancels, for the inline edit textarea
  // (.sp-edit-textarea).
  function handleEditTextareaKey(e){
    if(isImeComposing(e)) return;   // leave IME composition/cancellation keys to the IME
    if(e.key==='Escape'){
      e.preventDefault();
      editingId = null;
      renderPanel();
      return;
    }
    if(e.key==='Enter' && !e.shiftKey){
      e.preventDefault();
      var id = e.target.getAttribute('data-sp-cmt-id');
      var c = comments.filter(function(x){ return x.id===id; })[0];
      if(c) commitEdit(c, e.target);
    }
  }

  // Suppress the host page's own keyboard navigation while the JSON modal is open or while
  // typing into a text field. "c" toggles the panel, "j" opens the JSON modal, "a" opens the
  // comment box for the current selection (all disabled while typing / while the JSON modal is open).
  document.addEventListener('keydown', function(e){
    if(isJsonModalOpen()){
      e.stopPropagation();
      if(e.key==='Escape'){ closeJsonModal(); }
      return;
    }
    var tag = e.target && e.target.tagName;
    if(tag==='TEXTAREA' || tag==='INPUT'){
      e.stopPropagation();
      if(e.target === popupText){
        handlePopupTextareaKey(e);
      } else if(e.target.className && e.target.className.indexOf('sp-edit-textarea') !== -1){
        handleEditTextareaKey(e);
      }
      return;
    }
    if((e.key==='c' || e.key==='C') && !e.ctrlKey && !e.metaKey && !e.altKey){
      panel.classList.toggle('open');
      return;
    }
    if((e.key==='j' || e.key==='J') && !e.ctrlKey && !e.metaKey && !e.altKey){
      copyJsonShortcut();
      return;
    }
    if((e.key==='a' || e.key==='A') && !e.ctrlKey && !e.metaKey && !e.altKey){
      if(pendingSelection){
        e.preventDefault();   // prevents 'a' from landing in the textarea that gets focus
        e.stopPropagation();
        var ps = pendingSelection;
        pendingSelection = null;
        addPendingTarget(ps.unit, ps.unitLabel, {
          kind:'text-range', selectedText:ps.selectedText, contextBefore:ps.contextBefore, contextAfter:ps.contextAfter
        });
        showPopup();
      }
      return;
    }
    if((e.key==='e' || e.key==='E') && !e.ctrlKey && !e.metaKey && !e.altKey){
      e.preventDefault();
      var wasOpen = popupOpen;
      if(wasOpen) popup.style.visibility = 'hidden';   // hide the popup during picking; it would get in the way
      var restorePopupVisibility = function(){ if(wasOpen) popup.style.visibility = ''; };
      startPickMode(function(target, el, rect){
        restorePopupVisibility();
        var info = unitInfoFor(el);
        var unit = info ? info.unit : null;
        var unitLabel = info ? info.unitLabel : (target.kind==='document' ? 'Whole document' : '');
        addPendingTarget(unit, unitLabel, target);
        if(!wasOpen) showPopup(rect);
      }, restorePopupVisibility);
      return;
    }
  }, true);

  init();
})();
