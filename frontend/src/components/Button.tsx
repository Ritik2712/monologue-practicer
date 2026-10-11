import type { ComponentPropsWithoutRef, MouseEvent } from "react";

type Variant = "primary" | "secondary" | "danger";

const VARIANT_CLASSES: Record<Variant, string> = {
  primary:
    "border-transparent bg-indigo-700 text-white hover:bg-indigo-800 dark:bg-indigo-500 dark:text-zinc-950 dark:hover:bg-indigo-400",
  secondary:
    "border-zinc-300 bg-white text-zinc-900 hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800",
  danger:
    "border-red-300 bg-white text-red-800 hover:bg-red-50 dark:border-red-900 dark:bg-zinc-900 dark:text-red-300 dark:hover:bg-red-950",
};

type ButtonProps = Omit<ComponentPropsWithoutRef<"button">, "disabled"> & {
  variant?: Variant;
  disabled?: boolean;
};

/**
 * A disabled button stays focusable (aria-disabled instead of the disabled attribute), so
 * keyboard focus is not lost when an action switches itself off, e.g. Start after it is pressed.
 */
export function Button({
  variant = "secondary",
  disabled = false,
  className = "",
  onClick,
  type = "button",
  ...rest
}: ButtonProps) {
  const handleClick = (event: MouseEvent<HTMLButtonElement>) => {
    if (disabled) {
      event.preventDefault();
      return;
    }
    onClick?.(event);
  };

  return (
    <button
      type={type}
      aria-disabled={disabled || undefined}
      onClick={handleClick}
      className={`inline-flex min-h-11 items-center justify-center rounded-md border px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:focus-visible:outline-indigo-400 ${VARIANT_CLASSES[variant]} ${disabled ? "cursor-not-allowed opacity-50" : ""} ${className}`}
      {...rest}
    />
  );
}
