"use client";

interface WizardStepperProps {
  steps: string[];
  currentStep: number;
}

export function WizardStepper({ steps, currentStep }: WizardStepperProps) {
  return (
    <div className="flex items-center gap-2 mb-8">
      {steps.map((step, i) => (
        <div key={step} className="flex items-center gap-2">
          <div className="flex items-center gap-1.5">
            <div
              className={`
                w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-all duration-300
                ${
                  i < currentStep
                    ? "bg-cyan-500 text-gray-950"
                    : i === currentStep
                      ? "bg-cyan-400/20 text-cyan-400 border border-cyan-400"
                      : "bg-gray-800 text-gray-500"
                }
              `}
            >
              {i < currentStep ? "✓" : i + 1}
            </div>
            <span
              className={`text-xs hidden sm:inline ${
                i === currentStep ? "text-cyan-400" : "text-gray-500"
              }`}
            >
              {step}
            </span>
          </div>
          {i < steps.length - 1 && (
            <div
              className={`w-6 h-px ${
                i < currentStep ? "bg-cyan-500" : "bg-gray-700"
              }`}
            />
          )}
        </div>
      ))}
    </div>
  );
}
