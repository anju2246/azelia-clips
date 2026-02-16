import { useState, type ReactNode } from 'react';

/* ─── Card ─── */
interface CardProps {
    title?: string;
    description?: string;
    gradient?: boolean;
    badge?: string;
    badgeColor?: string;
    children: ReactNode;
    className?: string;
}

export function Card({ title, description, gradient, badge, badgeColor, children, className = '' }: CardProps) {
    return (
        <div className={`
      relative glass-card p-6
      ${gradient ? 'bg-gradient-to-br from-brand-400/10 to-brand-600/10 border-brand-400/20' : ''}
      ${className}
    `}>
            {badge && (
                <div className="absolute top-4 right-4">
                    <span className={`px-3 py-1 text-xs font-bold rounded-full text-white ${badgeColor || 'bg-gradient-to-r from-brand-400 to-brand-600'} shadow-lg shadow-brand-500/20`}>
                        {badge}
                    </span>
                </div>
            )}
            {(title || description) && (
                <div className="mb-4">
                    {title && <h3 className="text-base font-semibold text-zinc-100">{title}</h3>}
                    {description && <p className="text-sm text-zinc-400 mt-1">{description}</p>}
                </div>
            )}
            {children}
        </div>
    );
}

/* ─── Toggle ─── */
interface ToggleProps {
    label: string;
    description?: string;
    defaultChecked?: boolean;
    onChange?: (checked: boolean) => void;
    disabled?: boolean;
}

export function Toggle({ label, description, defaultChecked = false, onChange, disabled }: ToggleProps) {
    const [checked, setChecked] = useState(defaultChecked);

    const handleChange = () => {
        if (disabled) return;
        const newVal = !checked;
        setChecked(newVal);
        onChange?.(newVal);
    };

    return (
        <button
            onClick={handleChange}
            disabled={disabled}
            className={`w-full flex items-center justify-between gap-4 text-left ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
        >
            <div className="flex-1">
                <p className="text-sm font-medium text-zinc-100">{label}</p>
                {description && <p className="text-xs text-zinc-400 mt-0.5">{description}</p>}
            </div>
            <div className={`
        w-10 h-5 rounded-full transition-colors duration-200 relative flex-shrink-0
        ${checked ? 'bg-brand-400' : 'bg-white/10'}
      `}>
                <div className={`
          absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform duration-200 shadow-sm
          ${checked ? 'translate-x-5' : 'translate-x-0.5'}
        `} />
            </div>
        </button>
    );
}

/* ─── Segmented Control ─── */
interface SegmentedOption {
    value: string;
    label: string;
    icon?: string;
}

interface SegmentedProps {
    options: SegmentedOption[];
    defaultValue?: string;
    onChange?: (value: string) => void;
}

export function Segmented({ options, defaultValue, onChange }: SegmentedProps) {
    const [selected, setSelected] = useState(defaultValue || options[0].value);

    return (
        <div className="inline-flex bg-black/20 backdrop-blur-md rounded-lg p-1 gap-1 flex-wrap border border-white/5">
            {options.map((opt) => (
                <button
                    key={opt.value}
                    onClick={() => { setSelected(opt.value); onChange?.(opt.value); }}
                    className={`
            px-4 py-2 rounded-md text-sm font-medium transition-all duration-200
            ${selected === opt.value
                            ? 'bg-brand-400 text-brand-950 shadow-lg shadow-brand-400/20'
                            : 'text-zinc-400 hover:text-zinc-100 hover:bg-white/5'}
          `}
                >
                    {opt.icon && <span className="mr-1.5">{opt.icon}</span>}
                    {opt.label}
                </button>
            ))}
        </div>
    );
}

/* ─── Slider ─── */
interface SliderProps {
    label: string;
    min: number;
    max: number;
    defaultValue: number;
    unit?: string;
    step?: number;
    onChange?: (value: number) => void;
}

export function Slider({ label, min, max, defaultValue, unit = '', step = 1, onChange }: SliderProps) {
    const [value, setValue] = useState(defaultValue);

    return (
        <div>
            <div className="flex justify-between items-center mb-2">
                <label className="text-sm font-medium text-zinc-100">{label}</label>
                <span className="text-sm font-mono text-brand-400">{value}{unit}</span>
            </div>
            <input
                type="range"
                min={min}
                max={max}
                step={step}
                value={value}
                onChange={(e) => { const v = Number(e.target.value); setValue(v); onChange?.(v); }}
                className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer
          [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4
          [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-brand-400
          [&::-webkit-slider-thumb]:shadow-lg [&::-webkit-slider-thumb]:shadow-brand-400/30 [&::-webkit-slider-thumb]:cursor-pointer"
            />
        </div>
    );
}

/* ─── Info Box ─── */
interface InfoBoxProps {
    children: ReactNode;
    variant?: 'info' | 'warning' | 'experimental';
}

export function InfoBox({ children, variant = 'info' }: InfoBoxProps) {
    const styles = {
        info: 'bg-blue-500/10 border-blue-500/20 text-blue-300',
        warning: 'bg-amber-500/10 border-amber-500/20 text-amber-300',
        experimental: 'bg-brand-600/10 border-brand-600/20 text-brand-300',
    };

    return (
        <div className={`p-3 border rounded-lg ${styles[variant]}`}>
            <p className="text-sm">{children}</p>
        </div>
    );
}
