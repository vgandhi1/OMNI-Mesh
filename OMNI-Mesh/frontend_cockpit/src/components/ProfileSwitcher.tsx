import { PROFILES } from "../config/profiles";
import { useCockpitStore } from "../store/cockpitStore";

/**
 * Previews the per-profile UI labels. The *live* profile is whatever the connected
 * gateway runs (set by OMNI_MESH_PROFILE on the server); incoming frames re-sync this.
 */
export function ProfileSwitcher() {
  const currentProfile = useCockpitStore((s) => s.currentProfile);
  const initializeUI = useCockpitStore((s) => s.initializeUI);

  return (
    <div className="profile-switcher">
      {PROFILES.map((profile) => (
        <button
          key={profile}
          className={profile === currentProfile ? "profile-pill active" : "profile-pill"}
          onClick={() => initializeUI(profile)}
        >
          {profile}
        </button>
      ))}
    </div>
  );
}
