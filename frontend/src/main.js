import { Room, RoomEvent, Track } from 'livekit-client';
import './styles.css';

const $ = id => document.getElementById(id);
let room = null;
let muted = false;
let connecting = false;

function feedback(message) { $('feedback').textContent = message; }

function controls(connected) {
  $('connect').disabled = connected || connecting;
  $('access-token').disabled = connected || connecting;
  for (const id of ['microphone', 'sound', 'disconnect']) $(id).disabled = !connected;
  $('connection').textContent = connected ? 'Connected' : 'Disconnected';
  $('connection').classList.toggle('online', connected);
  if (!connected) {
    $('agent-state').textContent = 'Ready when you are';
    $('orb').classList.remove('speaking');
    $('room-label').textContent = 'A private room is created for each call.';
  }
}

function clearTranscript() {
  $('transcript').replaceChildren();
  $('empty').hidden = false;
}

function showTranscript(reader, participantInfo, activeRoom) {
  const row = document.createElement('article');
  const who = document.createElement('strong');
  const text = document.createElement('p');
  const trackId = reader.info.attributes?.['lk.transcribed_track_id'];
  const localTracks = [...activeRoom.localParticipant.audioTrackPublications.values()];
  who.textContent = localTracks.some(p => p.trackSid === trackId) || participantInfo.identity === activeRoom.localParticipant.identity ? 'You' : 'VoiceDesk';
  row.append(who, text);
  $('empty').hidden = true;
  $('transcript').append(row);
  while ($('transcript').children.length > 200) $('transcript').firstChild.remove();
  return text;
}

function configure(activeRoom) {
  activeRoom.on(RoomEvent.TrackSubscribed, track => {
    if (track.kind === Track.Kind.Audio) $('audio').append(track.attach());
  });
  activeRoom.on(RoomEvent.TrackUnsubscribed, track => {
    track.detach().forEach(element => element.remove());
  });
  activeRoom.on(RoomEvent.ParticipantAttributesChanged, (attributes) => {
    if (room !== activeRoom || !attributes['lk.agent.state']) return;
    const state = attributes['lk.agent.state'];
    const labels = { initializing: 'Getting ready…', listening: 'Listening to you', thinking: 'Working on that…', speaking: 'VoiceDesk is speaking', idle: 'Ready to listen' };
    $('agent-state').textContent = labels[state] || state;
    $('orb').classList.toggle('speaking', state === 'speaking');
  });
  activeRoom.on(RoomEvent.AudioPlaybackStatusChanged, () => {
    if (room === activeRoom && !activeRoom.canPlaybackAudio) feedback('Click Enable sound to hear the assistant.');
  });
  activeRoom.on(RoomEvent.Reconnecting, () => {
    if (room === activeRoom) $('connection').textContent = 'Reconnecting…';
  });
  activeRoom.on(RoomEvent.Reconnected, () => {
    if (room === activeRoom) $('connection').textContent = 'Connected';
  });
  activeRoom.on(RoomEvent.Disconnected, () => {
    if (room !== activeRoom) return;
    room = null;
    $('audio').replaceChildren();
    controls(false);
    feedback('Call ended.');
  });
  activeRoom.registerTextStreamHandler('lk.transcription', async (reader, participantInfo) => {
    if (room !== activeRoom) return;
    const text = showTranscript(reader, participantInfo, activeRoom);
    try {
      for await (const chunk of reader) {
        if (room !== activeRoom || !text.isConnected) break;
        text.textContent += chunk;
        $('transcript').scrollTop = $('transcript').scrollHeight;
      }
    } catch {
      if (text.isConnected) text.textContent += ' [transcript interrupted]';
    }
  });
}

$('connect-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (room || connecting) return;
  connecting = true;
  controls(false);
  feedback('Connecting to your private voice room…');
  const activeRoom = new Room({ audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  configure(activeRoom);
  room = activeRoom;
  try {
    const response = await fetch('/api/sessions', {
      method: 'POST', headers: { Authorization: `Bearer ${$('access-token').value}` },
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not create a session');
    clearTranscript();
    await activeRoom.connect(data.url, data.token);
    // Browser playback and microphone permissions are controlled by the caller.
    try { await activeRoom.startAudio(); } catch { /* Enable sound remains available. */ }
    await activeRoom.localParticipant.setMicrophoneEnabled(true);
    if (room !== activeRoom) throw new Error('The session disconnected during setup');
    muted = false;
    $('microphone').textContent = 'Mute microphone';
    $('access-token').value = '';
    controls(true);
    $('room-label').textContent = data.room;
    $('agent-state').textContent = 'Waiting for the assistant…';
    feedback(activeRoom.canPlaybackAudio ? 'Connected. You can speak or interrupt the assistant.' : 'Click Enable sound to hear the assistant.');
  } catch (error) {
    await activeRoom.disconnect();
    if (room === activeRoom) room = null;
    controls(false);
    feedback(error.message || 'Connection failed');
  } finally {
    connecting = false;
    controls(Boolean(room));
  }
});

$('microphone').addEventListener('click', async () => {
  const activeRoom = room;
  if (!activeRoom) return;
  try {
    await activeRoom.localParticipant.setMicrophoneEnabled(muted);
    if (room !== activeRoom) return;
    muted = !muted;
    $('microphone').textContent = muted ? 'Unmute microphone' : 'Mute microphone';
  } catch { feedback('Could not change the microphone. Check browser permissions.'); }
});
$('sound').addEventListener('click', async () => {
  try { await room?.startAudio(); feedback('Sound enabled.'); }
  catch { feedback('Audio playback is blocked. Check browser audio permissions.'); }
});
$('disconnect').addEventListener('click', async () => { await room?.disconnect(); });
$('clear').addEventListener('click', clearTranscript);
window.addEventListener('pagehide', () => { room?.disconnect(); });
