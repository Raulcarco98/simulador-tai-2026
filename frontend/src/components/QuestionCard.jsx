import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle, XCircle, ChevronLeft, ChevronRight } from "lucide-react";

export default function QuestionCard({
    question,
    onOptionSelect,
    selectedOption,
    showResult,
    onNext,
    onPrev,
    isFirst,
    isLast,
    onFinish
}) {

    return (
        <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            key={question.id}
            className="w-full max-w-3xl mx-auto p-5 md:p-8 rounded-2xl bg-white/70 dark:bg-[#0f172a]/60 backdrop-blur-xl border border-slate-200 dark:border-white/10 shadow-xl dark:shadow-2xl relative overflow-hidden transition-colors duration-300"
        >
            <div className="absolute top-0 right-0 w-64 h-64 bg-blue-500/10 rounded-full blur-3xl -z-10 transform translate-x-1/2 -translate-y-1/2" />

            <h2 className="text-lg md:text-2xl font-semibold text-slate-800 dark:text-slate-100 mb-6 leading-relaxed">
                {question.question}
            </h2>

            <div className="space-y-3 mb-8">
                {question.options.map((option, index) => {
                    let stateClass = "border-slate-200 dark:border-white/10 hover:bg-slate-50 dark:hover:bg-white/5 text-slate-700 dark:text-slate-300";
                    let icon = null;

                    if (selectedOption === index && !showResult) {
                        stateClass = "border-blue-500 shadow-[0_0_15px_rgba(59,130,246,0.3)] bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-200";
                    }

                    if (showResult) {
                        if (index === question.correct_index) {
                            stateClass = "border-emerald-500 bg-emerald-50 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-300";
                            icon = <CheckCircle className="w-5 h-5 ml-auto text-emerald-500 dark:text-emerald-400" />;
                        } else if (selectedOption === index) {
                            stateClass = "border-rose-500 bg-rose-50 dark:bg-rose-500/20 text-rose-700 dark:text-rose-300";
                            icon = <XCircle className="w-5 h-5 ml-auto text-rose-500 dark:text-rose-400" />;
                        } else {
                            stateClass = "border-slate-100 dark:border-white/5 opacity-50";
                        }
                    }

                    return (
                        <motion.button
                            key={index}
                            whileTap={!showResult ? { scale: 0.995 } : {}}
                            onClick={() => !showResult && onOptionSelect(index)}
                            disabled={showResult}
                            className={`w-full text-left p-4 rounded-xl border transition-all duration-300 flex items-center ${stateClass}`}
                        >
                            <span className="w-8 h-8 rounded-full border border-current/30 flex items-center justify-center mr-4 text-sm font-bold opacity-70 transition-all">
                                {String.fromCharCode(65 + index)}
                            </span>
                            <span className="flex-1">{option}</span>
                            {icon}
                        </motion.button>
                    );
                })}
            </div>

            <AnimatePresence>
                {showResult && (
                    <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        className="mb-8 p-4 bg-slate-50 dark:bg-slate-900/50 rounded-lg border border-slate-200 dark:border-white/5"
                    >
                        <h3 className="text-sm font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">Explicación Pro</h3>
                        <p className="text-slate-700 dark:text-slate-300 text-sm leading-relaxed mb-3">
                            {question.explanation}
                        </p>

                        {!question.isCorrect && selectedOption !== null && selectedOption !== question.correct_index && question.refutations && question.refutations[String(selectedOption)] && (
                            <motion.div
                                initial={{ opacity: 0, scale: 0.95 }}
                                animate={{ opacity: 1, scale: 1 }}
                                className="p-3 bg-rose-50 dark:bg-rose-900/20 border border-rose-100 dark:border-rose-900/30 rounded-lg"
                            >
                                <h4 className="text-xs font-bold text-rose-600 dark:text-rose-400 uppercase mb-1 flex items-center gap-2">
                                    <XCircle className="w-3 h-3" />
                                    Por qué fallaste:
                                </h4>
                                <p className="text-rose-800 dark:text-rose-200 text-sm italic">
                                    "{question.refutations[String(selectedOption)]}"
                                </p>
                            </motion.div>
                        )}
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Navigation Controls */}
            <div className="flex justify-between items-center mt-6 pt-6 border-t border-slate-200 dark:border-white/10">
                <button
                    onClick={onPrev}
                    disabled={isFirst}
                    className="flex items-center text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-white disabled:opacity-30 disabled:hover:text-slate-500 transition-colors"
                >
                    <ChevronLeft className="w-5 h-5 mr-1" />
                    Anterior
                </button>

                {isLast ? (
                    <button
                        onClick={onFinish}
                        className="px-6 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg font-bold shadow-lg shadow-emerald-500/20 transition-all"
                    >
                        Finalizar Examen
                    </button>
                ) : (
                    <button
                        onClick={onNext}
                        className="flex items-center text-blue-600 dark:text-blue-400 hover:text-blue-500 dark:hover:text-blue-300 transition-colors font-medium"
                    >
                        Siguiente
                        <ChevronRight className="w-5 h-5 ml-1" />
                    </button>
                )}
            </div>
        </motion.div>
    );
}
