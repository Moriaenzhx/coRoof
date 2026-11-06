"use client";

import { useId } from "react";
import "./companion-character.css";

/** Decorative presence. Its expressions never imply a model is running. */
export function CoRoofCharacter({
  state = "idle",
  paused = false,
}: {
  state?: "idle" | "attention" | "greeting";
  paused?: boolean;
}) {
  const id = `coroof-character-${useId().replace(/:/g, "")}`;

  return (
    <svg
      className="coroof-character"
      data-state={state}
      data-paused={paused}
      viewBox="0 0 80 96"
      width="80"
      height="96"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient
          id={`${id}-indigo`}
          x1="22"
          y1="8"
          x2="60"
          y2="76"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#727DAD" />
          <stop offset="0.5" stopColor="#4C5889" />
          <stop offset="1" stopColor="#333E6C" />
        </linearGradient>
        <linearGradient
          id={`${id}-cream`}
          x1="26"
          y1="17"
          x2="53"
          y2="48"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#FFFEF8" />
          <stop offset="0.6" stopColor="#FAF7EC" />
          <stop offset="1" stopColor="#EBE5D6" />
        </linearGradient>
        <linearGradient
          id={`${id}-coat`}
          x1="27"
          y1="51"
          x2="52"
          y2="78"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#FAFBFF" />
          <stop offset="0.65" stopColor="#E9ECF7" />
          <stop offset="1" stopColor="#D5DBEE" />
        </linearGradient>
        <linearGradient
          id={`${id}-glove`}
          x1="18"
          y1="60"
          x2="23"
          y2="72"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#FFFCF1" />
          <stop offset="1" stopColor="#E7E0D0" />
        </linearGradient>
        <radialGradient id={`${id}-shadow`}>
          <stop stopColor="#4D5779" stopOpacity="0.17" />
          <stop offset="1" stopColor="#4D5779" stopOpacity="0" />
        </radialGradient>
      </defs>

      <ellipse cx="40" cy="89" rx="22" ry="4.5" fill={`url(#${id}-shadow)`} />

      <g className="coroof-character-figure">
        <g fill={`url(#${id}-indigo)`}>
          <path d="M30 73h8v9c0 2-1.5 3.5-3.5 3.5H29c-2 0-3-1.5-2-3l3-3.5V73Z" />
          <path d="M42 73h8v6l3 3.5c1 1.5 0 3-2 3h-5.5c-2 0-3.5-1.5-3.5-3.5v-9Z" />
        </g>
        <path
          d="M29 83.5h6M46 83.5h5"
          stroke="#A7B0D0"
          strokeWidth="1"
          strokeLinecap="round"
          opacity="0.65"
        />

        <g>
          <path
            d="M27 54c-5 0-8 5-7 11"
            stroke={`url(#${id}-indigo)`}
            strokeWidth="8"
            strokeLinecap="round"
          />
          <path
            d="M18.5 62.5c2-.8 4 .2 4.7 2.3l.6 2c.6 2-1 4.1-3 4.1s-3.7-1.5-4-3.5l-.2-1.1c-.3-1.7.3-3.2 1.9-3.8Z"
            fill={`url(#${id}-glove)`}
            stroke="#DCD7CD"
            strokeWidth="0.6"
          />
        </g>

        <g className="coroof-character-wave">
          <path
            d="M53 54c5 0 8 5 7 11"
            stroke={`url(#${id}-indigo)`}
            strokeWidth="8"
            strokeLinecap="round"
          />
          <path
            d="M61.5 62.5c-2-.8-4 .2-4.7 2.3l-.6 2c-.6 2 1 4.1 3 4.1s3.7-1.5 4-3.5l.2-1.1c.3-1.7-.3-3.2-1.9-3.8Z"
            fill="#F5F0E3"
            stroke="#DCD7CD"
            strokeWidth="0.6"
          />
          <path
            d="m60 65.5-.3 2"
            stroke="#DCD5C5"
            strokeWidth="0.7"
            strokeLinecap="round"
          />
        </g>

        <path
          d="M29 49c-3 1-5 4-4.5 8L27 71c.6 5 4.5 7 13 7s12.4-2 13-7l2.5-14c.5-4-1.5-7-4.5-8H29Z"
          fill={`url(#${id}-coat)`}
          stroke="#CDD4E5"
          strokeWidth="0.8"
        />
        <path
          d="M29 51c3 4 7 6 11 6s8-2 11-6"
          stroke="#FFF"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <rect
          x="32"
          y="59"
          width="16"
          height="13"
          rx="4.5"
          fill="#F9FAFE"
          stroke="#D4DBEC"
          strokeWidth="0.7"
        />
        <path
          d="m35.5 64 4.5-3.5 4.5 3.5m-7.5-.2v4.2h6v-4.2"
          stroke="#6876A6"
          strokeWidth="1.3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path d="M34 44h12v7c-3 3-9 3-12 0v-7Z" fill="#E8E2D5" />

        <circle
          cx="22"
          cy="32"
          r="4"
          fill="#F2ECDD"
          stroke="#DBD5C9"
          strokeWidth="0.65"
        />
        <circle
          cx="58"
          cy="32"
          r="4"
          fill="#EEE8D9"
          stroke="#DBD5C9"
          strokeWidth="0.65"
        />
        <rect
          x="22"
          y="14"
          width="36"
          height="35"
          rx="15"
          fill={`url(#${id}-cream)`}
          stroke="#DFDACC"
          strokeWidth="0.8"
        />
        <path
          d="M27 21c3-3 7-4.5 12-4.5"
          stroke="#FFF"
          strokeWidth="2"
          strokeLinecap="round"
          opacity="0.85"
        />
        <ellipse
          cx="29.5"
          cy="37.5"
          rx="3"
          ry="1.5"
          fill="#E7BEAD"
          opacity="0.32"
        />
        <ellipse
          cx="50.5"
          cy="37.5"
          rx="3"
          ry="1.5"
          fill="#E7BEAD"
          opacity="0.32"
        />
        <g className="coroof-character-eyes">
          <rect
            x="30.5"
            y="29"
            width="4.5"
            height="6.5"
            rx="2.25"
            fill="#35416B"
          />
          <rect
            x="45"
            y="29"
            width="4.5"
            height="6.5"
            rx="2.25"
            fill="#35416B"
          />
          <circle cx="32" cy="30.7" r="0.7" fill="#FFF" opacity="0.9" />
          <circle cx="46.5" cy="30.7" r="0.7" fill="#FFF" opacity="0.9" />
        </g>
        <path
          d={state === "greeting" ? "M35.5 39q4.5 5 9 0" : "M36.5 39q3.5 3 7 0"}
          stroke="#6A6D7D"
          strokeWidth="1.4"
          strokeLinecap="round"
        />

        <path
          d="M18.5 15.5 37 4.5a5.8 5.8 0 0 1 6 0l18.5 11c1.9 1.2 1.1 4.1-1.2 4.1-.5 0-.9-.1-1.3-.4L41.5 9.5a3 3 0 0 0-3 0L21 19.2c-.4.3-.8.4-1.3.4-2.3 0-3.1-2.9-1.2-4.1Z"
          fill={`url(#${id}-indigo)`}
        />
        <path
          d="M21 15.8 38 5.8a4 4 0 0 1 4 0l17 10"
          stroke="#B1B9D8"
          strokeWidth="0.8"
          strokeLinecap="round"
          opacity="0.65"
        />
      </g>

      {state === "attention" && (
        <g className="coroof-character-attention">
          <circle
            cx="66"
            cy="22"
            r="6"
            fill="#FBF3E3"
            stroke="#E8D3AA"
            strokeWidth="0.8"
          />
          <circle cx="66" cy="22" r="2" fill="#B28B4E" />
        </g>
      )}
    </svg>
  );
}
