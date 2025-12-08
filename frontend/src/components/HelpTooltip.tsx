/**
 * HelpTooltip - A teal question mark icon that opens a help modal on click
 */

import { HelpCircle, X } from "lucide-react";
import { useState, useRef, useEffect } from "react";

interface HelpTooltipProps {
  content: string;
  className?: string;
}

export function HelpTooltip({ content, className = "" }: HelpTooltipProps) {
  const [isOpen, setIsOpen] = useState(false);
  const modalRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Close on click outside
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (event: MouseEvent) => {
      if (
        modalRef.current &&
        !modalRef.current.contains(event.target as Node) &&
        buttonRef.current &&
        !buttonRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [isOpen]);

  return (
    <div className={`relative inline-flex items-center ${className}`}>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="p-0.5 rounded-full hover:bg-tide-surface-light transition-colors focus:outline-none focus:ring-2 focus:ring-teal-500/50"
        aria-label="Help"
        aria-expanded={isOpen}
      >
        <HelpCircle className="w-5 h-5 text-teal-500" />
      </button>

      {isOpen && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" aria-hidden="true" />

          {/* Modal */}
          <div
            ref={modalRef}
            role="dialog"
            aria-modal="true"
            className="absolute z-50 w-72 top-full mt-2 right-0 bg-tide-surface border border-tide-border rounded-lg shadow-xl"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-3 py-2 border-b border-tide-border">
              <span className="text-sm font-medium text-teal-500">Help</span>
              <button
                onClick={() => setIsOpen(false)}
                className="p-1 rounded hover:bg-tide-surface-light transition-colors"
                aria-label="Close"
              >
                <X className="w-4 h-4 text-tide-text-muted" />
              </button>
            </div>

            {/* Content */}
            <div className="px-3 py-3">
              <p className="text-sm text-tide-text leading-relaxed">{content}</p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
