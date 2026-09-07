import test from 'node:test';
import assert from 'node:assert/strict';
import { captureStill } from '../src/capture.mjs';

function fixture() {
  const events = [];
  const video = { videoWidth: 1920, videoHeight: 1080, play: async () => {} };
  const canvas = { getContext: () => ({ drawImage: () => events.push('draw') }), toBlob: done => { events.push('encode'); done(new Blob(['image'])); } };
  const options = { mediaDevices: { getDisplayMedia: async () => ({ getTracks: () => [{ stop: () => events.push('stop') }] }) }, createElement: tag => tag === 'video' ? video : canvas, timeoutMs: 20 };
  return { events, video, canvas, options };
}

test('screen sharing stops before encoding starts, even if encoding remains pending', async () => {
  const f = fixture();
  let encode;
  f.canvas.toBlob = done => { encode = done; };
  const capture = captureStill(f.options);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(f.events, ['draw', 'stop']);
  assert.equal(f.video.srcObject, null);
  encode(new Blob(['image']));
  await capture;
  assert.deepEqual(f.events, ['draw', 'stop']);
});

test('picker cancellation creates no frame', async () => {
  const f = fixture();
  f.options.mediaDevices.getDisplayMedia = async () => { throw new DOMException('Cancelled', 'NotAllowedError'); };
  await assert.rejects(captureStill(f.options), { name: 'NotAllowedError' });
  assert.deepEqual(f.events, []);
});

for (const failure of ['play', 'draw', 'context', 'dimensions', 'encoding', 'timeout']) {
  test(`screen sharing stops after ${failure} failure`, async () => {
    const f = fixture();
    if (failure === 'play') f.video.play = async () => { throw new Error('play failed'); };
    if (failure === 'draw') f.canvas.getContext = () => ({ drawImage: () => { throw new Error('draw failed'); } });
    if (failure === 'context') f.canvas.getContext = () => null;
    if (failure === 'dimensions') f.video.videoWidth = 0;
    if (failure === 'encoding') f.canvas.toBlob = done => done(null);
    if (failure === 'timeout') f.video.play = () => new Promise(() => {});
    await assert.rejects(captureStill(f.options));
    assert.equal(f.events.filter(event => event === 'stop').length, 1);
    assert.equal(f.video.srcObject, null);
  });
}
