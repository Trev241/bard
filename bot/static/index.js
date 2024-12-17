const socket = io();

const PLAY_SVG = `
  <?xml version="1.0" encoding="utf-8"?>
  <svg class="w-12 fill-white" viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg">
    <title>Play</title>
    <path
      d="M133,440a35.37,35.37,0,0,1-17.5-4.67c-12-6.8-19.46-20-19.46-34.33V111c0-14.37,7.46-27.53,19.46-34.33a35.13,35.13,0,0,1,35.77.45L399.12,225.48a36,36,0,0,1,0,61L151.23,434.88A35.5,35.5,0,0,1,133,440Z" />
  </svg>
`;
const PAUSE_SVG = `
  <?xml version="1.0" encoding="utf-8"?>
  <svg class="w-12 fill-white" viewBox="0 0 32 32" version="1.1" xmlns="http://www.w3.org/2000/svg">
    <title>Pause</title>
    <path d="M5.92 24.096q0 0.832 0.576 1.408t1.44 0.608h4.032q0.832 0 1.44-0.608t0.576-1.408v-16.16q0-0.832-0.576-1.44t-1.44-0.576h-4.032q-0.832 0-1.44 0.576t-0.576 1.44v16.16zM18.016 24.096q0 0.832 0.608 1.408t1.408 0.608h4.032q0.832 0 1.44-0.608t0.576-1.408v-16.16q0-0.832-0.576-1.44t-1.44-0.576h-4.032q-0.832 0-1.408 0.576t-0.608 1.44v16.16z"></path>
  </svg>
`;

const log = (data) => {
  const logContainer = document.getElementById("logContainer");
  const messageElement = document.createElement("p");
  messageElement.textContent = data.message;
  logContainer.appendChild(messageElement);
  // messageElement.scrollIntoView();
  logContainer.scrollTop = logContainer.scrollHeight;
};

const updatePlaylist = (data) => {
  const tbElement = document.getElementById("nextUp");
  tbElement.innerHTML = "";
  let idx = 1;

  for (const track of data.queue.slice(1)) {
    tbElement.innerHTML += `
      <tr class="mb-6">
        <td class="pe-4 py-4 hidden md:table-cell">${idx}.</td>
        <td class="pb-4">
          <div class="flex items-center">
            <img class="w-36 md:w-52 rounded" src="${track.thumbnail}" />
            <div class="line-clamp-2">
              <h3 class="text-md font-semibold px-4">${track.title}</h3>
            </div>
          </div>
        </td>
        <td class="hidden font-extralight md:table-cell px-4 text-center">${track.duration}</td>
      </tr>
    `;

    idx++;
  }

  if (data.queue.length === 1) {
    tbElement.innerHTML += `
      <tr class="italic">
        <td class="text-center py-8 font-extralight" colspan="3">
          <p>Looks like nothing else is queued.</p>
          <p>Why not add another song?</p>
        </td>
      </tr>
    `;
  }
};

const updatePlayingNow = (data) => {
  if (document.getElementById("bannerVideo") || !data) {
    window.location.reload();
    return;
  }

  const imgElement = document.getElementById("nowPlayingImg");
  const ttlElement = document.getElementById("nowPlayingTtl");
  const spnElement = document.getElementById("requestedBy");
  const divElement = document.getElementById("backgroundImg");
  const pctElement = document.getElementById("pcNowPlaying");

  imgElement.setAttribute("src", data.thumbnail);
  ttlElement.setAttribute("href", data.webpage_url);
  ttlElement.textContent = data.title;
  pctElement.textContent = data.title;
  spnElement.innerHTML = `on ${data.requester}'s request`;
  divElement.style.backgroundImage = `url('${data.thumbnail}')`;
  btnPlay = PAUSE_SVG;

  updatePlaylist(data);
};

const updateCallMembers = (data) => {
  console.log("Message received");

  const ulElement = document.getElementById("callMemberList");
  ulElement.innerHTML = "";
  for (const member of data.members.slice(0, 3)) {
    ulElement.innerHTML += `
      <li class="flex items-center mb-2">
        <img class="rounded-full w-12" src="${member.avatar}" />
        <h3 class="ms-4">${member.display_name}</h3>
      </li>
    `;
  }

  if (data.members.length == 0) {
    ulElement.innerHTML = `
      <li class="flex justify-center items-center italic h-full">No one on call!</li>
    `;
  } else if (data.members.length > 3) {
    ulElement.innerHTML += `
      <li class="italic">
        and ${data.members.length - 3} more.
      </li>
    `;
  }
};

const setPlaybackCtrlsEnabled = (flag) => {
  const playbackControls = [
    document.getElementById("buttonPlay"),
    document.getElementById("buttonSkip"),
    document.getElementById("buttonLoop"),
  ];

  for (const control of playbackControls) {
    control.classList.toggle("hover:opacity-75", flag);
    control.classList.toggle("cursor-not-allowed", !flag);
    control.classList.toggle("opacity-75", !flag);

    if (!flag) control.setAttribute("disabled", "true");
    else control.removeAttribute("disabled");
    // control.classList.toggle("opacity", !flag);
  }
};

const setLooping = (flag) => {
  const btnLoop = document.getElementById("buttonLoop");
  btnLoop.innerHTML = `
    <?xml version="1.0" encoding="utf-8"?>
    <svg class="w-8 fill-white ${
      flag ? "opacity-100" : "opacity-75"
    }" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"
      enable-background="new 0 0 100 100" xml:space="preserve">
      <title>Loop</title>
      <path d="M76.5,58.3c0,0.1,0,0.2-0.1,0.2c-0.3,1.1-0.7,2.2-1.1,3.3c-0.5,1.2-1,2.3-1.6,3.4c-1.2,2.2-2.7,4.2-4.5,6
c-1.7,1.8-3.7,3.4-5.9,4.7c-2.2,1.3-4.5,2.3-7,3c-2.5,0.7-5.1,1.1-7.7,1.1C32.8,80,20,67.2,20,51.3s12.8-28.6,28.6-28.6
c5.3,0,10.3,1.5,14.6,4c0,0,0,0,0.1,0c2.1,1.2,4,2.7,5.6,4.4c0.5,0.4,0.8,0.7,1.2,1.2c0.9,0.8,1.6,0.3,1.6-0.9V22c0-1.1,0.9-2,2-2h4
c1.1,0,2,0.9,2.2,2v24.5c0,0.9-0.8,1.8-1.8,1.8H53.6c-1.1,0-1.9-0.8-1.9-1.9v-4.2c0-1.1,0.9-2,2-2h9.4c0.8,0,1.4-0.2,1.7-0.7
c-3.6-5-9.6-8.3-16.2-8.3c-11.1,0-20.1,9-20.1,20.1s9,20.1,20.1,20.1c8.7,0,16.1-5.5,18.9-13.3c0,0,0.3-1.8,1.7-1.8
c1.4,0,4.8,0,5.7,0c0.8,0,1.6,0.6,1.6,1.5C76.5,58,76.5,58.1,76.5,58.3z" />
    </svg>
  `;
};

const updatePlaybackState = (playing) => {
  const btnPlay = document.getElementById("buttonPlay");
  btnPlay.innerHTML = playing ? PAUSE_SVG : PLAY_SVG;
};

document.getElementById("buttonSkip").addEventListener("click", () => {
  socket.emit("playback_instruct_skip");
  setPlaybackCtrlsEnabled(false);
});

document.getElementById("buttonLoop").addEventListener("click", (data) => {
  socket.emit("playback_instruct_loop");
  setPlaybackCtrlsEnabled(false);
  setLooping(data.is_looping);
});

document.getElementById("buttonPlay").addEventListener("click", () => {
  socket.emit("playback_instruct_play");
  setPlaybackCtrlsEnabled(false);
});

// Register socket listeners
// socket.on("stdout_message", log);
// socket.on("stderr_message", log);
socket.on("playing_track", updatePlayingNow);
socket.on("playlist_update", updatePlaylist);
socket.on("playback_stop", () => window.location.reload());
socket.on("playback_instruct_done", () => setPlaybackCtrlsEnabled(true));
socket.on("playback_state", (state) => updatePlaybackState(state.playing));
// socket.on("call_list_update", updateCallMembers);
