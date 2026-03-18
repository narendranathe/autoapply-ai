import type { Variants, Transition } from "framer-motion";

export const mercuryRipple: Variants = {
  rest: { scale: 1, opacity: 1 },
  hover: { scale: 1.02, opacity: 0.95, transition: { duration: 0.25, ease: "easeOut" } },
};

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 16 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.35, ease: "easeOut" } },
};

export const streamToken: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.08 } },
};

const skeletonTransition: Transition = {
  duration: 1.6,
  repeat: Infinity,
  ease: "easeInOut",
};

export const skeletonPulse = {
  animate: {
    opacity: [0.15, 0.3, 0.15],
    transition: skeletonTransition,
  },
};
