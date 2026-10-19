import { useState } from "react";
import { Icon, type IconName } from "../icons";
import { readTheme, saveTheme, THEME_CHOICES, type ThemeChoice } from "../theme";

const OPTIONS: Record<ThemeChoice, { label: string; icon: IconName }> = {
  system: { label: "System theme", icon: "monitor" },
  light: { label: "Light theme", icon: "sun" },
  dark: { label: "Dark theme", icon: "moon" },
};

/** Three buttons in the header: follow the system, or always light, or always dark. */
export function ThemeSwitch() {
  const [choice, setChoice] = useState<ThemeChoice>(readTheme);
  return (
    <div className="theme-switch" role="group" aria-label="Theme">
      {THEME_CHOICES.map((option) => (
        <button
          key={option}
          type="button"
          aria-label={OPTIONS[option].label}
          title={OPTIONS[option].label}
          aria-pressed={choice === option}
          onClick={() => {
            saveTheme(option);
            setChoice(option);
          }}
        >
          <Icon name={OPTIONS[option].icon} size={16} />
        </button>
      ))}
    </div>
  );
}
