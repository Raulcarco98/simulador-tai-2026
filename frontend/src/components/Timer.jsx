import { motion } from "framer-motion";
import { useEffect, useState } from "react";

export default function Timer({ duration, onTimeUp, active }) {
    const [timeLeft, setTimeLeft] = useState(duration);

    useEffect(() => {
        if (!active) return;
        if (timeLeft <= 0) {
            onTimeUp();
            return;
        }

        const interval = setInterval(() => {
            setTimeLeft((prev) => prev - 1);
        }, 1000);

        return () => clearInterval(interval);
    }, [timeLeft, active, onTimeUp]);

    // Reset timer if duration changes
    useEffect(() => {
        setTimeLeft(duration);
    }, [duration]);

    const percentage = timeLeft / duration;
    const strokeDashoffset = 283 - (283 * percentage); // 2 * pi * 45 ≈ 283

    const formatTime = (seconds) => {
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
    };

    return (
        <div className="relative w-16 h-16 flex items-center justify-center">
            <svg className="w-full h-full transform -rotate-90">
                <circle
                    cx="32"
                    cy="32"
                    r="28"
                    stroke="currentColor"
                    strokeWidth="3"
                    fill="transparent"
                    className="text-slate-200 dark:text-slate-700 transition-colors duration-300"
                />
                <motion.circle
                    cx="32"
                    cy="32"
                    r="28"
                    stroke="currentColor"
                    strokeWidth="3"
                    fill="transparent"
                    strokeDasharray="283"
                    animate={{ strokeDashoffset }}
                    transition={{ duration: 1, ease: "linear" }}
                    className={timeLeft < 60 ? "text-rose-500" : "text-emerald-400"}
                />
            </svg>
            <span className="absolute text-sm font-bold text-slate-700 dark:text-slate-200 transition-colors duration-300">
                {formatTime(timeLeft)}
            </span>
        </div>
    );
}
