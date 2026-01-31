import { motion } from "framer-motion";
import { RefreshCcw, Home } from "lucide-react";

export default function Dashboard({ answers, questions, onRestart, onRetry }) {
    // Logic: Correct - (Errors / 3)
    const correctCount = answers.filter(a => a.isCorrect).length;
    const incorrectCount = answers.filter(a => a.answered && !a.isCorrect).length;
    const unansweredCount = questions.length - answers.length; // Or explicit unanswered

    const rawScore = correctCount - (incorrectCount / 3);
    const maxScore = questions.length;
    const percentageValue = Math.max(0, (rawScore / maxScore) * 100);
    const percentage = percentageValue.toFixed(1);

    // Chart calculation (Single Grade Progress)
    const scoreDeg = (percentageValue / 100) * 360;

    // Dynamic Color
    let progressColor = "#ef4444"; // Red (Fail)
    if (percentageValue >= 50) progressColor = "#fbbf24"; // Yellow (Pass)
    if (percentageValue >= 80) progressColor = "#10b981"; // Green (Good)

    const remainingColor = "#cbd5e1"; // Slate-300 for empty background

    return (
        <div className="flex flex-col items-center justify-center min-h-[60vh] text-center w-full max-w-4xl mx-auto">

            <div className="grid grid-cols-1 md:grid-cols-2 gap-12 items-center mb-12 w-full">

                {/* Left: Chart */}
                <div className="flex flex-col items-center">
                    <div className="relative w-48 h-48 rounded-full flex items-center justify-center shadow-2xl mb-6"
                        style={{
                            background: `conic-gradient(
                        ${progressColor} 0deg ${scoreDeg}deg,
                        ${remainingColor} ${scoreDeg}deg 360deg
                    )`
                        }}
                    >
                        <div className="absolute inset-2 bg-slate-50 dark:bg-[#020617] rounded-full flex flex-col items-center justify-center transition-colors duration-300">
                            <span className="text-xs text-slate-500 uppercase font-bold tracking-widest mb-1">Nota Final</span>
                            <span className="text-5xl font-black text-slate-900 dark:text-white transition-colors duration-300">{percentage}%</span>
                            <span className="text-sm text-slate-500 dark:text-slate-400 mt-2 font-mono">
                                {rawScore.toFixed(2)} / {maxScore} pts
                            </span>
                        </div>
                    </div>
                </div>

                {/* Right: Stats */}
                <div className="grid grid-cols-2 gap-4 w-full">
                    <StatCard label="Aciertos" value={correctCount} color="text-emerald-500 dark:text-emerald-400" bg="bg-emerald-500/10 border-emerald-500/20" />
                    <StatCard label="Fallos" value={incorrectCount} color="text-rose-500 dark:text-rose-400" bg="bg-rose-500/10 border-rose-500/20" />
                    <StatCard label="Sin Contestar" value={unansweredCount} color="text-slate-500 dark:text-slate-400" bg="bg-slate-200/50 dark:bg-slate-500/10 border-slate-300 dark:border-slate-500/20" />
                    <StatCard label="Penalización" value={`-${(incorrectCount / 3).toFixed(2)}`} color="text-orange-500 dark:text-orange-400" bg="bg-orange-500/10 border-orange-500/20" />
                </div>
            </div>

            <div className="flex gap-4">
                <button
                    onClick={onRetry}
                    className="flex items-center gap-2 px-8 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-full font-bold shadow-lg shadow-blue-500/25 transition-all transform hover:-translate-y-0.5 active:translate-y-0"
                >
                    <RefreshCcw className="w-4 h-4" />
                    Generar otro igual
                </button>
                <button
                    onClick={onRestart}
                    className="flex items-center gap-2 px-8 py-3 bg-slate-200 dark:bg-white/10 hover:bg-slate-300 dark:hover:bg-white/20 border border-slate-300 dark:border-white/10 rounded-full text-slate-900 dark:text-white transition-all font-semibold"
                >
                    <Home className="w-4 h-4" />
                    Volver al menú
                </button>
            </div>
        </div>
    );
}

function StatCard({ label, value, color, bg }) {
    return (
        <div className={`p-4 rounded-xl border ${bg} flex flex-col items-center`}>
            <span className={`text-2xl font-bold ${color}`}>{value}</span>
            <span className="text-xs text-slate-500 uppercase tracking-wide mt-1">{label}</span>
        </div>
    )
}
