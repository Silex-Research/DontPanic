/* Inline SVG icons — stroke-based, 16/18/20 sizes. All inherit currentColor. */

const Icon = ({ d, size = 16, fill = 'none', stroke = 'currentColor', sw = 1.6, style, children }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke={stroke} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" style={style}>
    {d ? <path d={d} /> : children}
  </svg>
);

const IconHome     = (p) => <Icon {...p}><path d="M3 11.5 12 4l9 7.5" /><path d="M5 10v9.5h14V10" /></Icon>;
const IconWork     = (p) => <Icon {...p}><rect x="3" y="4.5" width="18" height="15" rx="2" /><path d="M3 9h18" /><path d="M8 13h3M8 16h6" /></Icon>;
const IconCaps     = (p) => <Icon {...p}><path d="M12 3l8 4v6c0 4.5-3.5 7-8 8-4.5-1-8-3.5-8-8V7l8-4z" /><path d="m9 12 2.2 2.2L15.5 10" /></Icon>;
const IconHealth   = (p) => <Icon {...p}><path d="M3 12h4l2-5 4 10 2-5h6" /></Icon>;
const IconPrefs    = (p) => <Icon {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></Icon>;
const IconShield   = (p) => <Icon {...p}><path d="M12 3l8 4v6c0 4.5-3.5 7-8 8-4.5-1-8-3.5-8-8V7l8-4z" /></Icon>;
const IconCopy     = (p) => <Icon {...p}><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1" /></Icon>;
const IconCheck    = (p) => <Icon {...p}><path d="m5 12 5 5 9-11" /></Icon>;
const IconWarn     = (p) => <Icon {...p}><path d="M12 4 2.5 20h19L12 4z" /><path d="M12 10v5" /><circle cx="12" cy="17.5" r="0.5" fill="currentColor" /></Icon>;
const IconBlocked  = (p) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="m6 6 12 12" /></Icon>;
const IconClock    = (p) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></Icon>;
const IconExt      = (p) => <Icon {...p}><path d="M14 4h6v6" /><path d="m10 14 10-10" /><path d="M19 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h6" /></Icon>;
const IconArrowR   = (p) => <Icon {...p}><path d="M5 12h14M13 6l6 6-6 6" /></Icon>;
const IconChevR    = (p) => <Icon {...p}><path d="m9 6 6 6-6 6" /></Icon>;
const IconChevD    = (p) => <Icon {...p}><path d="m6 9 6 6 6-6" /></Icon>;
const IconDoc      = (p) => <Icon {...p}><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" /><path d="M14 3v5h5" /></Icon>;
const IconBranch   = (p) => <Icon {...p}><circle cx="6" cy="5" r="2" /><circle cx="6" cy="19" r="2" /><circle cx="18" cy="12" r="2" /><path d="M6 7v10" /><path d="M6 12c5 0 6-2 9-2" /></Icon>;
const IconUser     = (p) => <Icon {...p}><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 4-6 8-6s8 2 8 6" /></Icon>;
const IconRobot    = (p) => <Icon {...p}><rect x="4" y="8" width="16" height="11" rx="2" /><path d="M12 8V4" /><circle cx="12" cy="3" r="1" /><circle cx="9" cy="13" r="1" fill="currentColor" /><circle cx="15" cy="13" r="1" fill="currentColor" /></Icon>;
const IconRefresh  = (p) => <Icon {...p}><path d="M4 12a8 8 0 0 1 14-5l2-2" /><path d="M20 4v5h-5" /><path d="M20 12a8 8 0 0 1-14 5l-2 2" /><path d="M4 20v-5h5" /></Icon>;
const IconSearch   = (p) => <Icon {...p}><circle cx="11" cy="11" r="7" /><path d="m20 20-4.3-4.3" /></Icon>;
const IconFilter   = (p) => <Icon {...p}><path d="M3 5h18l-7 8v6l-4-2v-4z" /></Icon>;
const IconFolder   = (p) => <Icon {...p}><path d="M3 6a1 1 0 0 1 1-1h5l2 2h8a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6z" /></Icon>;
const IconKey      = (p) => <Icon {...p}><circle cx="8" cy="15" r="4" /><path d="m11 12 9-9" /><path d="m16 7 3 3" /></Icon>;
const IconGear     = IconPrefs;
const IconBell     = (p) => <Icon {...p}><path d="M6 9a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8z" /><path d="M10 21a2 2 0 0 0 4 0" /></Icon>;
const IconPause    = (p) => <Icon {...p}><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></Icon>;
const IconPlay     = (p) => <Icon {...p}><path d="m7 5 12 7-12 7V5z" /></Icon>;
const IconFlag     = (p) => <Icon {...p}><path d="M4 21V4h14l-3 5 3 5H4" /></Icon>;
const IconCircle   = (p) => <Icon {...p}><circle cx="12" cy="12" r="9" /></Icon>;
const IconDot      = ({ size = 6, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 6 6"><circle cx="3" cy="3" r="3" fill={color} /></svg>
);
const IconAgent    = (p) => <Icon {...p}><path d="M12 2 4 6v6c0 4.4 3.4 8 8 10 4.6-2 8-5.6 8-10V6l-8-4z" /><circle cx="12" cy="11" r="2.4" /><path d="M8 17c1-2 2.5-3 4-3s3 1 4 3" /></Icon>;
const IconArch     = (p) => <Icon {...p}><circle cx="5" cy="6" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="5" cy="18" r="2" /><circle cx="19" cy="18" r="2" /><path d="M7 6h3M14 6h3M7 18h3M14 18h3" /><path d="M5 8v8M19 8v8" /><path d="m7 7 3.5 3.5M16.5 10.5 13.5 13.5M7 17l3.5-3.5M16.5 13.5 13.5 10.5" /></Icon>;
const IconLink     = (p) => <Icon {...p}><path d="M10 14a4 4 0 0 1 0-5.6l3-3a4 4 0 0 1 5.6 5.6l-1.5 1.5" /><path d="M14 10a4 4 0 0 1 0 5.6l-3 3a4 4 0 0 1-5.6-5.6L7 11.5" /></Icon>;

Object.assign(window, {
  Icon, IconHome, IconWork, IconCaps, IconHealth, IconPrefs, IconShield,
  IconCopy, IconCheck, IconWarn, IconBlocked, IconClock, IconExt,
  IconArrowR, IconChevR, IconChevD, IconDoc, IconBranch, IconUser, IconRobot,
  IconRefresh, IconSearch, IconFilter, IconFolder, IconKey, IconGear,
  IconBell, IconPause, IconPlay, IconFlag, IconCircle, IconDot, IconAgent, IconLink, IconArch
});
