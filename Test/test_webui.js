/* 다빈치 코드 웹 클라이언트(game.html) 클릭 UI 검증.
 *
 * 브라우저 없이 jsdom 으로 실제 DOM 을 만들어
 *   1) 추측 모드 : 상대 카드 클릭 가능 / 값 버튼 생성 / 클릭 시 올바른 입력 전송
 *   2) 조커 슬롯 : ▶ 화살표 생성 / 클릭 시 슬롯 번호 전송
 *   3) 조커 앞뒤 : [앞]/[뒤] 버튼 생성 / 클릭 시 0·1 전송
 *   4) 결과 표시 : 정답 → 빨간 O, 오답 → 파란 X
 * 를 확인한다.
 *
 * 실행:  cd C:\Suzuha\DavinciOnline && node test_webui.js
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const HTML = fs.readFileSync(path.join(__dirname, 'web', 'game.html'), 'utf8');

let fails = 0;
function chk(name, cond, extra) {
  console.log((cond ? '  PASS ' : '  FAIL ') + name + (extra ? `  (${extra})` : ''));
  if (!cond) fails++;
}

/* ---------- 상태 샘플 만들기 ---------- */
function stateGuess(extraAsk) {
  const ask = Object.assign({
    mode: 'guess',
    prompt: '>> 추측: ...',
    targets: [
      { seat: 1, pos: 1, is_black: true },
      { seat: 1, pos: 2, is_black: false },
      { seat: 1, pos: 3, is_black: true },
      { seat: 1, pos: 4, is_black: false },
    ],
    values: ['1w', '3b', '5w', 'Jb', 'aw'],
  }, extraAsk || {});
  return {
    round: 1, deck: 16, viewer: 0, waiting_name: null, spectating: false,
    public: ['8b'], ranking: {},
    ask,
    players: [
      { seat: 0, name: '태원', is_human: true, is_me: true, is_eliminated: false,
        hidden_count: 5, revealed_count: 0,
        cards: [
          { value: '2b', is_black: true, is_joker: false, revealed: false, star: false },
          { value: '5w', is_black: false, is_joker: false, revealed: false, star: true },
        ] },
      { seat: 1, name: 'CPU1', is_human: false, is_me: false, is_eliminated: false,
        hidden_count: 4, revealed_count: 1,
        cards: [
          { value: null, is_black: true, is_joker: false, revealed: false, star: false },
          { value: null, is_black: false, is_joker: false, revealed: false, star: false },
          { value: null, is_black: true, is_joker: false, revealed: false, star: false },
          { value: null, is_black: false, is_joker: false, revealed: false, star: false },
          { value: '8b', is_black: true, is_joker: false, revealed: true, star: false },
        ] },
    ],
  };
}

/* ---------- DOM 준비 (fetch/폴링 스텁) ---------- */
function makeDom() {
  const dom = new JSDOM(HTML, { runScripts: 'dangerously', pretendToBeVisual: true });
  const w = dom.window;
  // ★ 폴링(setTimeout)을 막아 테스트가 스스로 상태를 주입하게 한다.
  w.setTimeout = () => 0;
  // ★ 사운드(SFX)용 Audio 스텁 — jsdom 엔 Audio 가 없다.
  //   play() 는 Promise 를 돌려주므로 then/catch 를 흉내낸다.
  w.Audio = class {
    constructor(src) { this.src = src; this.volume = 1; this.muted = false;
                       this.currentTime = 0; this.preload = ''; }
    play() { return Promise.resolve(); }
    pause() {}
  };
  w.__replies = [];
  w.__state = null;
  w.fetch = (url, opts) => {
    const u = String(url);
    if (u.includes('/api/reply')) {
      const body = JSON.parse(opts.body);
      w.__replies.push(body.text);
      return Promise.resolve({ json: () => Promise.resolve({ ok: true }) });
    }
    if (u.includes('/api/chat')) {
      const body = JSON.parse(opts.body);
      w.__chats.push(body.text);
      return Promise.resolve({ json: () => Promise.resolve({ ok: true }) });
    }
    // /api/state
    const d = {
      connected: true, seat: 0, name: (w.__name !== undefined ? w.__name : '태원'),
      state: w.__state,
      // ★ __msgsIn 으로 로그를 주입할 수 있다 (CPU 추리 결과음 검증용).
      messages: w.__msgsIn || [], msg_total: (w.__msgsIn || []).length,
      chats: w.__chatsIn || [], chat_total: (w.__chatsIn || []).length,
      ask: w.__state ? w.__state.ask : null, ask_prompt: w.__askPrompt || null,
      ended: !!w.__ended, end_text: '',
    };
    return Promise.resolve({ json: () => Promise.resolve(d) });
  };
  w.__chats = [];
  w.__askPrompt = null;
  w.__name = undefined;      // ★ undefined = 기본('태원'), null = 이름 미정(이름 단계)
  w.__ended = false;
  w.__msgsIn = null;         // ★ 주입 로그 (기본 없음)
  return dom;
}

function renderInto(w, st) {
  w.__state = st;
  w.render(st);
}

function flush(w) {
  // 폴링이 setTimeout 으로 계속 돌므로 microtask 만 흘려보낸다.
  return new Promise(r => setTimeout(r, 10));
}

(async () => {
  console.log('== 1) 추측 모드 ==');
  let dom = makeDom();
  let w = dom.window;
  renderInto(w, stateGuess());
  await flush(w);

  const picks = w.document.querySelectorAll('.tile.pick');
  chk('상대 미공개 카드 4장이 클릭 가능', picks.length === 4, `${picks.length}개`);
  const chipEls = [...w.document.querySelectorAll('.valbar .vchip')];
  const chips = chipEls.map(c => c.textContent);
  chk('값 버튼 생성', chips.length === 5, chips.join(','));
  chk('값 버튼 라벨은 색문자 없이 (w/b 제거)',
      JSON.stringify(chips) === JSON.stringify(['1', '3', '5', 'J', 'a']), chips.join(','));
  chk('값 버튼 원본 값(dataset.val)은 유지',
      JSON.stringify(chipEls.map(c => c.dataset.val)) ===
      JSON.stringify(['1w', '3b', '5w', 'Jb', 'aw']),
      chipEls.map(c => c.dataset.val).join(','));
  chk('프롬프트가 클릭 안내', /클릭/.test(w.document.getElementById('prompt').textContent));

  // 상대 2번째 카드(자리2) 클릭 → armed
  picks[1].dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
  await flush(w);
  chk('클릭한 카드에 armed 표시',
      w.document.querySelectorAll('.tile.armed').length === 1);
  chk('프롬프트가 "값 버튼을 누르세요"로 변경',
      /값 버튼/.test(w.document.getElementById('prompt').textContent));

  // 값 '3b' 칩 클릭 → "2 2 3b" 전송 (seat1→상대번호2, pos2)
  const chip3b = chipEls.find(c => c.dataset.val === '3b');
  chip3b.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
  await flush(w);
  chk('카드 클릭 + 값 클릭 → 올바른 추측 전송',
      w.__replies.includes('2 2 3b'), JSON.stringify(w.__replies));

  // 값 먼저 누르면 안내만 (전송 안 됨)
  const dom2 = makeDom(); const w2 = dom2.window;
  renderInto(w2, stateGuess());
  await flush(w2);
  const chip0 = [...w2.document.querySelectorAll('.valbar .vchip')]
                  .find(c => c.dataset.val === '1w');
  chip0.dispatchEvent(new w2.MouseEvent('click', { bubbles: true }));
  await flush(w2);
  chk('카드 없이 값만 누르면 전송하지 않음',
      w2.__replies.length === 0 && /먼저 상대 카드/.test(w2.document.getElementById('prompt').textContent));

  console.log('\n== 2) 조커 슬롯 모드 ==');
  const dom3 = makeDom(); const w3 = dom3.window;
  renderInto(w3, stateGuess({
    mode: 'joker_slot',
    data: { slots: 2, joker: 'Jb', cards: ['2b', '5w'] },
  }));
  await flush(w3);
  const arrows = w3.document.querySelectorAll('.slot-arrow.on');
  chk('▼ 화살표가 카드 사이에 생성 (M+1 = 3개)', arrows.length === 3, `${arrows.length}개`);
  chk('화살표 문자는 ▼ (아래 방향)', arrows[0].textContent === '▼', arrows[0].textContent);
  chk('값 버튼은 숨김', !w3.document.getElementById('valbar').classList.contains('on'));
  arrows[0].dispatchEvent(new w3.MouseEvent('click', { bubbles: true }));
  await flush(w3);
  chk('앞쪽 화살표 클릭 → 슬롯 0 전송', w3.__replies.includes('0'), JSON.stringify(w3.__replies));
  arrows[2].dispatchEvent(new w3.MouseEvent('click', { bubbles: true }));
  await flush(w3);
  chk('뒤쪽 화살표 클릭 → 슬롯 2 전송', w3.__replies.includes('2'), JSON.stringify(w3.__replies));

  console.log('\n== 3) 조커 앞/뒤 모드 ==');
  const dom4 = makeDom(); const w4 = dom4.window;
  renderInto(w4, stateGuess({
    mode: 'joker_side',
    data: { wall: 'Jb', ncard: '5b', cards: ['2b', 'Jb', '7b'] },
  }));
  await flush(w4);
  const sp = w4.document.querySelector('.seat.bottom .side-pick');
  chk('[앞]/[뒤] 버튼 표시', sp.classList.contains('on') && sp.querySelectorAll('button').length === 2,
      `${sp.querySelectorAll('button').length}개`);
  const btns = sp.querySelectorAll('button');
  chk('새 카드 값이 버튼에 안내됨', /5b/.test(btns[0].textContent), btns[0].textContent);
  btns[0].dispatchEvent(new w4.MouseEvent('click', { bubbles: true }));
  await flush(w4);
  chk('[앞] 클릭 → 0 전송', w4.__replies.includes('0'), JSON.stringify(w4.__replies));
  btns[1].dispatchEvent(new w4.MouseEvent('click', { bubbles: true }));
  await flush(w4);
  chk('[뒤] 클릭 → 1 전송', w4.__replies.includes('1'), JSON.stringify(w4.__replies));

  console.log('\n== 4) 결과 표시 (O / X) ==');
  const dom5 = makeDom(); const w5 = dom5.window;
  w5.showVerdict(true);
  await flush(w5);
  const big = w5.document.getElementById('bigverdict');
  // ★ EHone 요청: 패산 위 작은 O/X 는 제거하고 큰 하나만 띄운다.
  chk('패산 위 작은 O/X 요소는 없다', w5.document.getElementById('verdict') === null);
  chk('정답 → 큰 표시가 ok + show',
      big.classList.contains('ok') && big.classList.contains('show'));
  chk('정답 마크가 ○', big.querySelector('.mark').textContent === '○',
      big.querySelector('.mark').textContent);
  // 확대 애니메이션 유지 확인 (pop 애니메이션이 걸려 있어야 함)
  const bigCss = w5.document.querySelector('style').textContent;
  chk('큰 표시에 pop 애니메이션 유지',
      bigCss.includes('.big-verdict.show') && bigCss.includes('animation:pop'));
  chk('화면에 O/X 표시 요소가 1개뿐',
      w5.document.querySelectorAll('.big-verdict').length === 1 &&
      w5.document.querySelectorAll('.verdict').length === 0,
      'big=' + w5.document.querySelectorAll('.big-verdict').length +
      ' small=' + w5.document.querySelectorAll('.verdict').length);

  // ★ EHone 요청: 오른쪽 위 워터마크 "EHone 개발"
  const cred = w5.document.getElementById('credit');
  const credCss = w5.document.querySelector('style').textContent;
  chk('오른쪽 위 워터마크 존재 + 문구', cred !== null && cred.textContent === 'EHone 개발');
  chk('워터마크는 회색 계열 + 작은 글씨',
      credCss.includes('.topbar .credit') && credCss.includes('font-size:11px'),
      credCss.match(/\.topbar \.credit[^}]*}/)?.[0]?.replace(/\s+/g, ' '));
  chk('워터마크가 topbar 안 (오른쪽 끝)', cred.parentElement.classList.contains('topbar'));
  w5.showVerdict(false);
  await flush(w5);
  chk('오답 → no 로 전환 (ok 제거)',
      big.classList.contains('no') && !big.classList.contains('ok'));
  chk('오답 마크가 ✕', big.querySelector('.mark').textContent === '✕',
      big.querySelector('.mark').textContent);

  console.log('\n== 5) 로그 문구에서 정답/오답 감지 ==');
  const dom6 = makeDom(); const w6 = dom6.window;
  w6.__state = stateGuess();
  w6.pushLog('✔ 정답! 태원 가 (2 2 3b) 추측 → 3b 공개.');
  w6.showVerdict(true);
  await flush(w6);
  chk('정답 로그 → O 표시 (큰 표시)', w6.document.getElementById('bigverdict').classList.contains('ok'));
  w6.pushLog('✘ 오답! CPU1 의 추측(...) — 벌칙: 4b 공개.');
  w6.showVerdict(false);
  await flush(w6);
  chk('오답 로그 → X 표시 (큰 표시)', w6.document.getElementById('bigverdict').classList.contains('no'));

  console.log('\n== 6) 게임 종료 → 패산 제거 + 순위표 ==');
  const dom7 = makeDom(); const w7 = dom7.window;
  const endState = stateGuess();
  endState.ranking = { '1': 1, '0': 2, '2': 3 };
  endState.players = [
    { seat: 0, name: '태원', is_human: true, is_me: true, is_eliminated: true,
      hidden_count: 2, revealed_count: 3, cards: [] },
    { seat: 1, name: 'CPU1', is_human: false, is_me: false, is_eliminated: false,
      hidden_count: 4, revealed_count: 0, cards: [] },
    { seat: 2, name: 'CPU2', is_human: false, is_me: false, is_eliminated: true,
      hidden_count: 0, revealed_count: 5, cards: [] },
  ];
  w7.showRankboard(endState);
  await flush(w7);
  const rb = w7.document.getElementById('rankboard');
  chk('순위표 표시', rb.classList.contains('on'));
  const rows = [...rb.querySelectorAll('.rb-row')];
  chk('순위표 3행', rows.length === 3, `${rows.length}행`);
  chk('1등이 맨 위 + first 강조',
      rows[0].classList.contains('first') && /CPU1/.test(rows[0].textContent),
      rows[0].textContent.trim());
  chk('내 행에 me 표시',
      rows.some(r => r.classList.contains('me') && /태원/.test(r.textContent)));
  chk('★ 패산(노란 오브젝트) 제거됨',
      w7.document.getElementById('yama').style.display === 'none',
      w7.document.getElementById('yama').style.display);

  console.log('\n== 7) 게임 입력 버튼화 (검은카드수 · 계속/그만 · 공개자리) ==');
  // 7-1 검은 카드 수
  const dom8 = makeDom(); const w8 = dom8.window;
  renderInto(w8, stateGuess({ mode: 'black_count', data: { max: 3 } }));
  await flush(w8);
  const cb = w8.document.getElementById('choicebar');
  chk('choicebar 표시', cb.classList.contains('on'));
  const bcBtns = [...cb.querySelectorAll('.cbtn')];
  chk('0~3 버튼 4개', bcBtns.length === 4, bcBtns.map(b => b.textContent).join(','));
  chk('텍스트 입력창 비활성', w8.document.getElementById('input').disabled);
  bcBtns[2].dispatchEvent(new w8.MouseEvent('click', { bubbles: true }));
  await flush(w8);
  chk('버튼 클릭 → "2" 전송', w8.__replies.includes('2'), JSON.stringify(w8.__replies));

  // 7-2 계속/그만
  const dom9 = makeDom(); const w9 = dom9.window;
  renderInto(w9, stateGuess({ mode: 'more_guess' }));
  await flush(w9);
  const mgBtns = [...w9.document.getElementById('choicebar').querySelectorAll('.cbtn')];
  chk('계속/그만 버튼 2개', mgBtns.length === 2, mgBtns.map(b => b.textContent).join(','));
  mgBtns[1].dispatchEvent(new w9.MouseEvent('click', { bubbles: true }));
  await flush(w9);
  chk('그만 클릭 → "q" 전송', w9.__replies.includes('q'), JSON.stringify(w9.__replies));

  // 7-3 공개할 자리
  const dom10 = makeDom(); const w10 = dom10.window;
  renderInto(w10, stateGuess({ mode: 'fail_reveal', data: { hidden: [2, 5] } }));
  await flush(w10);
  const frBtns = [...w10.document.getElementById('choicebar').querySelectorAll('.cbtn')];
  chk('공개 자리 버튼 2개', frBtns.length === 2, frBtns.map(b => b.textContent).join(','));
  frBtns[1].dispatchEvent(new w10.MouseEvent('click', { bubbles: true }));
  await flush(w10);
  chk('자리 5 클릭 → "5" 전송', w10.__replies.includes('5'), JSON.stringify(w10.__replies));

  console.log('\n== 8) 텍스트바 = 이름 입력 → 채팅 전환 ==');
  const dom11 = makeDom(); const w11 = dom11.window;
  // 이름 ASK 가 도착한 상태를 만들고 실제 폴링 경로로 한 번 돌린다.
  // ★ __name=null 이 '아직 이름이 없음' → 이름 입력 단계를 뜻한다.
  w11.__name = null;
  w11.__askPrompt = '이름을 입력하세요 (Enter=기본):';
  // poll 이 setTimeout 으로 재귀하므로 1회분만 직접 호출한다.
  await w11.pollOnce();
  const inp = w11.document.getElementById('input');
  chk('이름 단계에서 입력창 활성', !inp.disabled);
  chk('이름 단계 placeholder', inp.placeholder === '이름을 입력하세요', inp.placeholder);
  inp.value = '태원';
  w11.document.getElementById('send').dispatchEvent(new w11.MouseEvent('click', { bubbles: true }));
  await flush(w11);
  chk('이름이 게임 입력(/api/reply)으로 전송', w11.__replies.includes('태원'),
      JSON.stringify(w11.__replies));
  // 이름을 보냈으니 서버가 이제 이름을 확정해 준다 (실제 동작과 동일하게 흉내).
  w11.__name = '태원';
  await w11.pollOnce();
  chk('이름 전송 후 채팅 모드', w11.isChatReady() === true, String(w11.isChatReady()));

  // 8-2 ★ --name 접속: relay 가 이름 ASK 를 보내도 서버가 자동응답하므로
  //     브라우저는 이름이 이미 있다 → '이름 입력' 대신 채팅 모드여야 한다.
  const dom11b = makeDom(); const w11b = dom11b.window;
  w11b.__name = '태원';
  w11b.__askPrompt = '이름을 입력하세요 (Enter=기본, 60초):';
  await w11b.pollOnce();
  const inpB = w11b.document.getElementById('input');
  chk('--name 접속: placeholder 가 채팅', inpB.placeholder === '채팅 메시지 (Enter)', inpB.placeholder);
  chk('--name 접속: 채팅 모드', w11b.isChatReady() === true, String(w11b.isChatReady()));

  inp.value = '안녕하세요!';
  inp.dispatchEvent(new w11.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  await flush(w11);
  chk('채팅은 /api/chat 으로 전송', w11.__chats.includes('안녕하세요!'),
      JSON.stringify(w11.__chats));
  chk('채팅이 게임 입력으로 새지 않음',
      !w11.__replies.includes('안녕하세요!'), JSON.stringify(w11.__replies));

  // 채팅 렌더 ('[이름] 내용' 파싱 + 내 메시지 표시)
  w11.pushChat('[Suzuha] 반가워요~');
  await flush(w11);
  const cl = w11.document.getElementById('chatlog');
  chk('채팅 한 줄 표시', cl.querySelectorAll('.cline').length === 1);
  chk('채팅 이름이 노란 강조', /Suzuha/.test(cl.querySelector('.cname').textContent),
      cl.querySelector('.cname').textContent.trim());
  w11.pushChat('[태원] 저도 반가워요');
  await flush(w11);
  const last = cl.querySelectorAll('.cline')[1];
  chk('내 메시지는 me 클래스', last.classList.contains('me'), last.className);

  // ★ 9) 패산 위 정보 바 (차례 + 라운드·덱·공개) — EHone 요청
  console.log('\n== 9) 패산 위 정보 바 ==');
  const ydom = makeDom(); const yw = ydom.window;
  const yst = stateGuess();
  yst.round = 4; yst.deck = 2; yst.public = ['0w','1b','2w']; yst.waiting_name = null;
  yw.__state = yst;
  yw.render(yst);
  const yturnEl = yw.document.getElementById('yturn');
  const ystatEl = yw.document.getElementById('ystat');
  chk('정보 바 요소 존재', !!yturnEl && !!ystatEl);
  chk('내 차례일 때 "내 차례"', yturnEl.textContent === '내 차례', yturnEl.textContent);
  chk('라운드·덱·공개 표시',
      ystatEl.textContent.replace(/\s+/g, '') === '라운드4·덱2장·공개3장',
      ystatEl.textContent);
  chk('상단 오른쪽(#sub)은 비어 중복 없음',
      yw.document.getElementById('sub').textContent === '',
      yw.document.getElementById('sub').textContent);
  // 남의 차례
  yst.waiting_name = 'CPU1';
  yw.render(yst);
  chk('남의 차례일 때 "CPU1 차례"',
      yturnEl.textContent === 'CPU1 차례', yturnEl.textContent);
  // 관전(탈락)
  yst.spectating = true; yst.waiting_name = null;
  yw.render(yst);
  chk('관전 중 표시', yturnEl.textContent === '관전 중', yturnEl.textContent);
  // 공개 0장이면 공개 항목 생략
  yst.spectating = false; yst.public = [];
  yw.render(yst);
  chk('공개 0장이면 공개 항목 생략',
      !/공개/.test(ystatEl.textContent), ystatEl.textContent);
  // 정보 바가 패산(.yama) 안에 있어야 정렬이 맞는다
  chk('정보 바가 .yama 안에 위치',
      yw.document.getElementById('yamainfo').closest('.yama') !== null);

  // ★ 10) 다른 사람(CPU) 추리 결과에 소리 — EHone 요청
  console.log('\n== 10) CPU 추리 결과음 ==');
  const sdom = makeDom(); const sw = sdom.window;
  sw.__name = '태원';
  const sst = stateGuess();
  sw.__state = sst; sw.render(sst);
  // SFX.play 를 관찰 가능하게 감싼다
  sw.eval('window.__sfxSeen=[]; (function(){var o=SFX.play; SFX.play=function(n){window.__sfxSeen.push(n);return o.apply(SFX,arguments);};})()');
  // (a) 남의 추리(정답) 로그 → 소리가 나야 한다
  //     ⚠️ 첫 pollOnce 에서는 myName 이 아직 null 이라 비교가 안 된다.
  //        실제 플레이에서도 이름 확정 뒤부터 동작하므로, 먼저 한 번 폴링해
  //        이름을 확정시킨 뒤 주입한다.
  sw.__msgsIn = [];
  await sw.pollOnce();                 // 이름 확정
  sw.eval('window.__sfxSeen=[]');
  sw.__msgsIn = ['\n✔ 정답! CPU1 가 (#2 태원의 패) 자리 1 = 0w 추측 → 0w 공개.'];
  await sw.pollOnce();
  const seenA = sw.eval('window.__sfxSeen.slice()');
  chk('CPU 추리 결과에 소리 발생', seenA.includes('select'), JSON.stringify(seenA));
  // (b) 내 추리 로그 → 소리를 내면 안 된다(내가 이미 냈다)
  sw.eval('window.__sfxSeen=[]');
  sw.__msgsIn = ['\n✔ 정답! 태원 가 (#2 CPU1의 패) 자리 1 = 0w 추측 → 0w 공개.'];
  await sw.pollOnce();
  const seenB = sw.eval('window.__sfxSeen.slice()');
  chk('내 추리 로그에는 소리 없음', !seenB.includes('select'), JSON.stringify(seenB));

  // ★ 11) 남의 비밀 조커에 노란 테두리가 붙으면 안 된다 — EHone 요청(최중요)
  //   ★ 서버(session.py)가 '볼 수 없는 카드'의 is_joker 를 False 로 내려준다.
  //     여기서는 그렇게 내려온 상태를 그대로 그려서 테두리가 안 붙는지 본다.
  console.log('\n== 11) 조커 비밀 유지 ==');
  const jdom = makeDom(); const jw = jdom.window;
  jw.__name = '태원';
  const jst = stateGuess();
  // 서버가 마스킹한 상태를 재현: 남의 비밀 카드는 value=null, is_joker=false
  const opp = jst.players.find(p => !p.is_me);
  opp.cards[0].is_joker = false;
  opp.cards[0].value = null;
  // 내 패 조커는 그대로 보여야 한다
  const me = jst.players.find(p => p.is_me);
  me.cards[0].is_joker = true;
  me.cards[0].value = 'Jw';
  jw.__state = jst; jw.render(jst);
  const jokerEls = Array.from(jw.document.querySelectorAll('.tile.joker'));
  chk('남의 비밀 조커는 노란 테두리 없음', jokerEls.length === 1,
      `tile.joker=${jokerEls.length} (기대 1 = 내 조커만)`);
  chk('내 조커는 노란 테두리 유지',
      jokerEls.length === 1 && jokerEls[0].textContent.includes('J'),
      jokerEls.map(e => e.textContent).join(','));

  // ★ 12) 덱 소진 시 벌칙 버튼에 실제 값 표시 — EHone 요청
  console.log('\n== 12) 벌칙 버튼에 값 표시 ==');
  const fdom = makeDom(); const fw = fdom.window;
  fw.__name = '태원';
  const fst = stateGuess({ mode: 'fail_reveal',
                           data: { hidden: [1, 3, 4], values: ['2b', 'aw', 'Jb'] } });
  fw.__state = fst; fw.render(fst);
  const frBtnList = Array.from(fw.document.getElementById('choicebar').querySelectorAll('.cbtn'))
                      .map(b => b.textContent.trim());
  // ★ 자리번호 없이 '패의 값'만 보여준다 (EHone 요청). 웹은 색을 배경으로 구분: 2b->2, aw->a, Jb->J
  chk('버튼 라벨이 값만 (자리번호 없음)', frBtnList.length === 3 &&
      frBtnList[0] === '2' && frBtnList[1] === 'a' && frBtnList[2] === 'J',
      JSON.stringify(frBtnList));
  chk('버튼에 자리번호 문구 없음', !frBtnList.some(t => t.includes('자리')),
      JSON.stringify(frBtnList));
  // 카드 색 클래스가 붙는지 (검정/흰색)
  const frBtnEls = Array.from(fw.document.getElementById('choicebar').querySelectorAll('.cbtn'));
  chk('값에 카드 색 클래스 부여', frBtnEls[0].classList.contains('cardlike') &&
      frBtnEls[0].classList.contains('b') &&
      frBtnEls[1].classList.contains('w'),
      frBtnEls.map(e => e.className).join(' | '));
  // ★ 버튼을 실제로 눌러 '자리번호'가 전송되는지 본다(표시는 값이지만 전송은 자리).
  chk('버튼 클릭 시 자리번호 전송', (() => {
    const b = frBtnEls[1];              // 3번째 hidden = 3
    b.dispatchEvent(new fw.MouseEvent('click', { bubbles: true }));
    return Array.isArray(fw.__replies) && fw.__replies.includes('3');
  })(), JSON.stringify(fw.__replies));

  console.log('\n' + '='.repeat(50));
  console.log(fails === 0 ? 'ALL PASS ✅' : `FAIL (${fails}개)`);
  process.exit(fails === 0 ? 0 : 1);
})();
