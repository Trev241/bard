const socket = io();

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
  }

  const imgElement = document.getElementById("nowPlayingImg");
  const ttlElement = document.getElementById("nowPlayingTtl");
  const spnElement = document.getElementById("requestedBy");
  const divElement = document.getElementById("backgroundImg");

  imgElement.setAttribute("src", data.thumbnail);
  ttlElement.setAttribute("href", data.webpage_url);
  ttlElement.textContent = data.title;
  spnElement.innerHTML = `on ${data.requester}'s request`;
  divElement.style.backgroundImage = `url('${data.thumbnail}')`;

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

// socket.on("stdout_message", log);
// socket.on("stderr_message", log);
socket.on("playing_track", updatePlayingNow);
socket.on("playlist_update", updatePlaylist);
socket.on("playback_stop", () => window.location.reload());
// socket.on("call_list_update", updateCallMembers);
