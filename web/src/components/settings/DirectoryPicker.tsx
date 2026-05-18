import React, { useState, useEffect } from "react";
import {
  Folder,
  FolderOpen,
  ChevronRight,
  ArrowUp,
  Loader2,
  X,
  Check,
} from "lucide-react";
import { supabase } from "../../lib/supabase";

interface DirEntry {
  name: string;
  path: string;
  has_children: boolean;
}

interface BrowseResponse {
  path: string;
  parent: string | null;
  dirs: DirEntry[];
  error?: string;
}

interface DirectoryPickerProps {
  isOpen: boolean;
  currentPath: string;
  onSelect: (path: string) => void;
  onClose: () => void;
}

const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || "/api";

export const DirectoryPicker: React.FC<DirectoryPickerProps> = ({
  isOpen,
  currentPath,
  onSelect,
  onClose,
}) => {
  const [browsePath, setBrowsePath] = useState("~");
  const [dirs, setDirs] = useState<DirEntry[]>([]);
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [resolvedPath, setResolvedPath] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (isOpen) {
      // Start from current path if set, otherwise home
      const startPath = currentPath && currentPath !== "" ? currentPath : "~";
      loadDirectory(startPath);
    }
  }, [isOpen]);

  const loadDirectory = async (path: string) => {
    setIsLoading(true);
    setError("");
    try {
      const { data: authData } = await supabase.auth.getSession();
      const token = authData?.session?.access_token;
      const res = await fetch(
        `${API_BASE}/browse?path=${encodeURIComponent(path)}`,
        {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        },
      );
      const data: BrowseResponse = await res.json();

      if (!res.ok || data.error) {
        setError(data.error || "Failed to browse directory");
        setDirs([]);
      } else {
        setDirs(data.dirs ?? []);
      }
      setResolvedPath(data.path ?? path);
      setParentPath(data.parent ?? null);
      setBrowsePath(data.path ?? path);
    } catch (e) {
      setError("Failed to browse directory");
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-zinc-900 border border-white/10 rounded-2xl w-full max-w-xl shadow-2xl flex flex-col max-h-[80vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/5">
          <h3 className="text-white font-semibold text-lg">
            Select Podcast Directory
          </h3>
          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-white transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Current Path Bar */}
        <div className="px-5 py-3 bg-black/30 border-b border-white/5 flex items-center gap-2">
          {parentPath && (
            <button
              onClick={() => loadDirectory(parentPath)}
              className="p-1.5 hover:bg-white/10 rounded-lg transition-colors text-zinc-400 hover:text-white cursor-pointer"
              title="Go up"
            >
              <ArrowUp className="w-4 h-4" />
            </button>
          )}
          <code className="text-sm text-brand-400 font-mono truncate flex-1">
            {resolvedPath}
          </code>
        </div>

        {/* Directory List */}
        <div className="flex-1 overflow-y-auto min-h-[200px] max-h-[400px]">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-6 h-6 text-brand-500 animate-spin" />
            </div>
          ) : error ? (
            <div className="text-center py-12 text-red-400 text-sm">
              {error}
            </div>
          ) : dirs.length === 0 ? (
            <div className="text-center py-12 text-zinc-500 text-sm">
              No subdirectories
            </div>
          ) : (
            <div className="py-1">
              {dirs.map((dir) => (
                <button
                  key={dir.path}
                  onClick={() => loadDirectory(dir.path)}
                  className="w-full px-5 py-2.5 flex items-center gap-3 hover:bg-white/5 transition-colors text-left cursor-pointer group"
                >
                  <Folder className="w-4 h-4 text-zinc-500 group-hover:text-brand-400 transition-colors flex-shrink-0" />
                  <span className="text-sm text-zinc-300 group-hover:text-white transition-colors truncate flex-1">
                    {dir.name}
                  </span>
                  {dir.has_children && (
                    <ChevronRight className="w-4 h-4 text-zinc-600 flex-shrink-0" />
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Footer: Select this folder */}
        <div className="px-5 py-4 border-t border-white/5 flex items-center justify-between">
          <p className="text-xs text-zinc-500">
            Navigate to your episodes folder, then click Select
          </p>
          <button
            onClick={() => {
              onSelect(resolvedPath);
              onClose();
            }}
            className="flex items-center gap-2 px-5 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-xl font-medium text-sm transition-colors cursor-pointer"
          >
            <Check className="w-4 h-4" />
            Select This Folder
          </button>
        </div>
      </div>
    </div>
  );
};
