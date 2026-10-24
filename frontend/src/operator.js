import { Room, RoomEvent, Track } from 'livekit-client';
import './styles.css';
const $ = id => document.getElementById(id);
let room;
async function request(path, method = 'GET') {
  const response = await fetch(path, {method, headers: {Authorization: `Bearer ${$('token').value}`}});
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || 'Queue request failed');
  return result;
}
$('refresh').onclick = async () => {
  try {
    const {handoffs} = await request('/api/handoffs');
    $('queue').replaceChildren();
    for (const item of handoffs) {
      const row = document.createElement('li'), button = document.createElement('button');
      row.textContent = `${item.room} · ${item.reason} · ${item.state} `;
      button.textContent = 'Join caller';
      button.onclick = async () => {
        if (room) return;
        button.disabled = true;
        let active;
        try {
          const data = await request(`/api/handoffs/${item.id}/join`, 'POST');
          active = new Room(); room = active;
          active.on(RoomEvent.TrackSubscribed, track => {
            if (track.kind === Track.Kind.Audio) $('audio').append(track.attach());
          });
          active.on(RoomEvent.TrackUnsubscribed, track => track.detach().forEach(el => el.remove()));
          active.on(RoomEvent.Disconnected, () => {
            if (room === active) room = null;
            $('audio').replaceChildren();
          });
          await active.connect(data.url, data.token);
          await active.startAudio();
          await active.localParticipant.setMicrophoneEnabled(true);
          $('status').textContent = `Connected to ${data.room}. Verify any uncertain booking with the calendar before reserving another slot.`;
        } catch (error) {
          await active?.disconnect(); room = null;
          $('status').textContent = error.message;
        } finally { button.disabled = false; }
      };
      row.append(button); $('queue').append(row);
    }
    $('status').textContent = `${handoffs.length} pending handoffs`;
  } catch (error) { $('status').textContent = error.message; }
};
$('disconnect').onclick = () => room?.disconnect();
window.addEventListener('pagehide', () => room?.disconnect());
