#!/usr/bin/env node
// VISONSDK ドローン制御クライアント (Node.js)
// iPhone上のTCPサーバー (port 8080) にJSONコマンドを送って制御する
//
// 事前準備:
//   $ brew install libimobiledevice
//   $ iproxy 8080 8080    ← iPhoneの8080をPCのlocalhost:8080に転送
//
// 起動:
//   $ node drone-client.js               # 対話モード（キーボード操作）
//   $ node drone-client.js demo          # デモシーケンス自動実行
//   $ HOST=127.0.0.1 PORT=8080 node drone-client.js

const net = require('net');
const readline = require('readline');

const HOST = process.env.HOST || '127.0.0.1';
const PORT = parseInt(process.env.PORT || '8080', 10);
const MODE = process.argv[2] || 'interactive';

// ====== TCP接続 ============================================================

const client = new net.Socket();
let connected = false;

client.connect(PORT, HOST, () => {
  connected = true;
  console.log(`✅ 接続: ${HOST}:${PORT}`);
  if (MODE === 'demo') {
    runDemo().catch(e => console.error('demo error:', e));
  } else {
    startInteractive();
  }
});

let rxBuf = '';
client.on('data', (data) => {
  rxBuf += data.toString('utf8');
  let nl;
  while ((nl = rxBuf.indexOf('\n')) >= 0) {
    const line = rxBuf.slice(0, nl);
    rxBuf = rxBuf.slice(nl + 1);
    if (!line) continue;
    try {
      const resp = JSON.parse(line);
      printResp(resp);
    } catch {
      console.log('←', line);
    }
  }
});

client.on('error', (err) => {
  console.error('❌ 接続エラー:', err.message);
  console.error('   iproxyが起動しているか確認: `iproxy 8080 8080`');
  process.exit(1);
});

client.on('close', () => {
  console.log('🔌 接続終了');
  process.exit(0);
});

// ====== 送信ヘルパ =========================================================

function send(cmd) {
  if (!connected) return;
  const line = JSON.stringify(cmd) + '\n';
  client.write(line);
  // 受信時にしか出力しないので、ここでは送ったコマンドだけ表示
  process.stdout.write(`→ ${JSON.stringify(cmd)}\n`);
}

function printResp(resp) {
  // 対話モード中はステータス更新だけコンパクトに
  if (resp.ok === true && resp.cmd) {
    // 短いackなので静かに
    process.stdout.write(`  ✓ ${resp.cmd}\n`);
  } else {
    process.stdout.write(`← ${JSON.stringify(resp)}\n`);
  }
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

// ====== デモシーケンス =====================================================

async function runDemo() {
  console.log('\n=== デモシーケンス ===');
  console.log('5秒後に離陸します。緊急停止は Ctrl+C\n');
  await sleep(2000);

  send({cmd: 'status'});
  await sleep(500);

  send({cmd: 'gyro_cal'});
  await sleep(2000);

  console.log('🛫 離陸');
  send({cmd: 'takeoff'});
  await sleep(5000);

  console.log('⬆️ 上昇 2秒');
  send({cmd: 'stick', roll: 0, pitch: 0, throttle: 40, yaw: 0});
  await sleep(2000);

  console.log('🔼 前進 2秒');
  send({cmd: 'stick', roll: 0, pitch: 40, throttle: 0, yaw: 0});
  await sleep(2000);

  console.log('↪️ 右旋回 2秒');
  send({cmd: 'stick', roll: 0, pitch: 0, throttle: 0, yaw: 50});
  await sleep(2000);

  console.log('🟢 中立 1秒');
  send({cmd: 'neutral'});
  await sleep(1000);

  console.log('🛬 着陸');
  send({cmd: 'land'});
  await sleep(3000);

  send({cmd: 'neutral'});
  console.log('=== デモ終了 ===');
  process.exit(0);
}

// ====== 対話モード (キーボード) ============================================

function startInteractive() {
  console.log(`
==== 対話モード ====
  t : 🛫 離陸          l : 🛬 着陸           x : ⏹  緊急停止
  w/s : 前進/後退      a/d : 左移動/右移動
  q/e : 左旋回/右旋回  r/f : 上昇/下降
  ↑↓←→: 前後左右        n/space : 中立
  p : 撮影             i : ライト           g : ジャイロ校正
  v : ステータス       Ctrl+C : 終了
`);

  readline.emitKeypressEvents(process.stdin);
  if (process.stdin.isTTY) process.stdin.setRawMode(true);

  const NUDGE_MS = 600;
  const STICK_VAL = 50;
  let pending = null; // 中立タイマー

  const stickHold = (axis, value) => {
    if (pending) clearTimeout(pending);
    const cmd = {cmd: 'stick', roll: 0, pitch: 0, throttle: 0, yaw: 0};
    cmd[axis] = value;
    send(cmd);
    pending = setTimeout(() => {
      send({cmd: 'neutral'});
      pending = null;
    }, NUDGE_MS);
  };

  process.stdin.on('keypress', (str, key) => {
    if (key.ctrl && key.name === 'c') { client.end(); return; }

    switch (key.name) {
      case 't':     send({cmd: 'takeoff'}); break;
      case 'l':     send({cmd: 'land'}); break;
      case 'x':     send({cmd: 'emergency'}); break;
      case 'p':     send({cmd: 'photo'}); break;
      case 'i':     send({cmd: 'light'}); break;
      case 'g':     send({cmd: 'gyro_cal'}); break;
      case 'v':     send({cmd: 'status'}); break;
      case 'b':     send({cmd: 'flip'}); break;
      case 'n':
      case 'space': send({cmd: 'neutral'}); if (pending) {clearTimeout(pending); pending=null;} break;

      case 'w': case 'up':    stickHold('pitch',     STICK_VAL); break;
      case 's': case 'down':  stickHold('pitch',    -STICK_VAL); break;
      case 'a': case 'left':  stickHold('roll',     -STICK_VAL); break;
      case 'd': case 'right': stickHold('roll',      STICK_VAL); break;
      case 'q':               stickHold('yaw',      -STICK_VAL); break;
      case 'e':               stickHold('yaw',       STICK_VAL); break;
      case 'r':               stickHold('throttle',  STICK_VAL); break;
      case 'f':               stickHold('throttle', -STICK_VAL); break;
    }
  });
}
