document.addEventListener("DOMContentLoaded", (event) => {
  gsap.registerPlugin(
    Flip,
    ScrollTrigger,
    Observer,
    ScrollToPlugin,
    Draggable,
    MotionPathPlugin,
    EaselPlugin,
    TextPlugin,
    RoughEase,
    ExpoScaleEase,
    SlowMo,
    CustomEase
  );

  let currentScroll = 0;
  let scrollDirection = 1;

  let loops = gsap.utils.toArray(".abilities").map((line, i) => {
    const links = line.querySelectorAll(".ability");
    return horizontalLoop(links, {
      repeat: -1,
      speed: 1.5 + i * 0.5,
      reversed: false,
      paused: true,
      paddingRight: parseFloat(gsap.getProperty(links[0], "marginRight", "px")),
    });
  });

  window.addEventListener("scroll", () => {
    let direction = window.scrollY > currentScroll ? 1 : -1;
    if (direction !== scrollDirection) {
      console.log("change", direction);
      loops.forEach((tl) => {
        gsap.to(tl, { timeScale: direction, overwrite: true });
      });
      scrollDirection = direction;
    }
    currentScroll = window.scrollY;
  });

  gsap.fromTo(
    ".header-item",
    { opacity: 0 },
    { opacity: 1, ease: "power4.in", stagger: 0.25 }
  );

  gsap.to(".header-item-word", {
    color: "#DB9E3D",
    delay: 4,
    stagger: 0.15,
  });

  gsap.to(".header-item-word", {
    color: "black",
    delay: 5,
    stagger: 0.15,
  });
  gsap.to(".header-item-title", { color: "#DB9E3D", delay: 4, stagger: 0.1 });

  gsap.fromTo(
    ".ability",
    { opacity: 0 },
    {
      opacity: 1,
      ease: "power4.out",
      delay: 3,
      stagger: {
        amount: 0.1,
        from: "end",
      },
      ease: "power4.out",
    }
  );

  gsap.fromTo("#img-main", { width: "0%" }, { width: "100%", delay: 1.5 });

  gsap.fromTo(
    ".abilities-container",
    { width: "0%", padding: "2rem 0" },
    {
      width: "100%",
      padding: "2rem",
      delay: 2,
      onComplete: () => loops.forEach((tl) => tl.resume()),
    }
  );
});
