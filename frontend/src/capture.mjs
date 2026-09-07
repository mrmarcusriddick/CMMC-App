// Release screen sharing as soon as the still frame is copied, before encoding or upload.
export async function captureStill({ mediaDevices = navigator.mediaDevices, createElement = tag => document.createElement(tag), timeoutMs = 15000 } = {}) {
  let stream;
  let video;
  let timer;
  const stop = () => {
    stream?.getTracks().forEach(track => track.stop());
    stream = null;
    if (video) video.srcObject = null;
  };
  try {
    stream = await mediaDevices.getDisplayMedia({ video: true, audio: false });
    video = createElement('video');
    video.srcObject = stream;
    video.muted = true;
    await Promise.race([
      video.play(),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('The selected screen did not provide a frame. Please try again.')), timeoutMs); }),
    ]);
    clearTimeout(timer);
    if (!video.videoWidth || !video.videoHeight) throw new Error('The selected screen did not provide a frame.');
    const scale = Math.min(1, 2560 / Math.max(video.videoWidth, video.videoHeight));
    const canvas = createElement('canvas');
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    const context = canvas.getContext('2d');
    if (!context) throw new Error('The browser could not prepare the capture image.');
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    stop();
    const image = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
    if (!image) throw new Error('The browser did not return a screenshot image.');
    return image;
  } finally {
    clearTimeout(timer);
    stop();
  }
}
