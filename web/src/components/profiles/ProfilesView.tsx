import React from "react";
import { ProfilesPanel } from "./ProfilesPanel";

/**
 * Full-page Podcasts view — same layout language as the Settings page
 * (centered column + header), so profile management feels like a normal
 * dashboard window, not a popup.
 */
export const ProfilesView: React.FC = () => {
  return (
    <div className="max-w-4xl mx-auto pb-12">
      <div className="mb-8">
        <h2 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-zinc-400">
          Podcasts
        </h2>
        <p className="text-zinc-500 mt-2">
          Cada podcast es un espacio aislado: sus clips, transcripciones y cuenta
          de Claude no se mezclan. Cambia entre ellos o crea uno nuevo.
        </p>
      </div>

      <ProfilesPanel />
    </div>
  );
};
