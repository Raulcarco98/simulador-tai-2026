import { useState } from 'react';
import { motion } from 'framer-motion';
import { Play, Settings2, BookOpen, BarChart } from 'lucide-react';
import UploadZone from './UploadZone';

export default function StartScreen({ onStart }) {
    const [numQuestions, setNumQuestions] = useState(10);
    const [minutes, setMinutes] = useState(15);
    const [file, setFile] = useState(null);
    const [topic, setTopic] = useState("");
    const [difficulty, setDifficulty] = useState("Intermedio");

    const handleStart = () => {
        onStart({ numQuestions, minutes, file, topic, difficulty });
    };

    return (
        <div className="w-full max-w-5xl mx-auto flex flex-col lg:flex-row gap-12 items-start">

            {/* Left Column: Intro */}
            <div className="flex-1 text-left pt-4">
                <motion.div
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.5 }}
                >
                    <div className="inline-block px-3 py-1 mb-4 text-xs font-semibold tracking-wider text-blue-600 dark:text-blue-400 uppercase bg-blue-100 dark:bg-blue-400/10 rounded-full border border-blue-200 dark:border-blue-400/20">
                        TAI Pro 2026 - v2.2 Universal
                    </div>
                    <h1 className="text-4xl md:text-6xl font-black text-slate-900 dark:text-white mb-6 leading-tight tracking-tight">
                        Estudia <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-indigo-600 dark:from-blue-400 dark:to-indigo-400">Cualquier Tema</span> con IA
                    </h1>
                    <p className="text-slate-600 dark:text-slate-400 text-lg mb-8 leading-relaxed max-w-lg">
                        Sube tus apuntes o simplemente escribe un tema. Nuestro algoritmo generará un examen personalizado al instante.
                    </p>
                </motion.div>
            </div>

            {/* Right Column: Settings Card */}
            <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.2 }}
                className="w-full lg:w-[500px] bg-white/70 dark:bg-[#0f172a]/80 backdrop-blur-xl border border-slate-200 dark:border-white/10 rounded-3xl p-8 shadow-2xl dark:shadow-none relative overflow-hidden"
            >
                <div className="absolute top-0 right-0 w-32 h-32 bg-indigo-500/5 dark:bg-indigo-500/10 rounded-full blur-3xl -z-10 transform translate-x-1/2 -translate-y-1/2" />

                <div className="space-y-8">

                    {/* Source Selection Group */}
                    <div className="space-y-4">
                        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                            <BookOpen className="w-4 h-4" /> Fuente de Conocimiento
                        </h3>

                        {/* 1. Upload */}
                        <div className={topic ? "opacity-50 grayscale transition-all" : "transition-all"}>
                            <UploadZone onFileChange={setFile} />
                        </div>

                        <div className="relative flex items-center justify-center">
                            <div className="h-px bg-slate-200 dark:bg-white/10 w-full absolute"></div>
                            <span className="bg-white dark:bg-[#0f172a] px-3 text-xs text-slate-400 relative z-10 font-bold uppercase">O escribe un tema</span>
                        </div>

                        {/* 2. Topic Input */}
                        <div className={file ? "opacity-50 pointer-events-none transition-all" : "transition-all"}>
                            <textarea
                                value={topic}
                                onChange={(e) => setTopic(e.target.value)}
                                placeholder="Ej: Historia del Arte, Python Avanzado, Constitución Española..."
                                rows={2}
                                className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-white rounded-xl px-4 py-3 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all font-medium resize-none placeholder:text-slate-400"
                            />
                        </div>
                    </div>

                    {/* Exam Config Group */}
                    <div className="space-y-4">
                        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                            <BarChart className="w-4 h-4" /> Parámetros del Examen
                        </h3>

                        <div className="grid grid-cols-2 gap-4">
                            {/* Num Questions */}
                            <div className="relative">
                                <select
                                    value={numQuestions}
                                    onChange={(e) => setNumQuestions(Number(e.target.value))}
                                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-white rounded-xl px-4 py-3 appearance-none focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all font-medium text-sm"
                                >
                                    <option value="5">5 preguntas</option>
                                    <option value="10">10 preguntas</option>
                                    <option value="20">20 preguntas</option>
                                </select>
                                <div className="absolute inset-y-0 right-0 flex items-center px-2 pointer-events-none">
                                    <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path></svg>
                                </div>
                            </div>

                            {/* Difficulty */}
                            <div className="relative">
                                <select
                                    value={difficulty}
                                    onChange={(e) => setDifficulty(e.target.value)}
                                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-white rounded-xl px-4 py-3 appearance-none focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all font-medium text-sm"
                                >
                                    <option value="Básico">Nivel Básico</option>
                                    <option value="Intermedio">Nivel Intermedio</option>
                                    <option value="Experto">Nivel Experto</option>
                                </select>
                                <div className="absolute inset-y-0 right-0 flex items-center px-2 pointer-events-none">
                                    <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path></svg>
                                </div>
                            </div>
                        </div>
                    </div>

                    <button
                        onClick={handleStart}
                        disabled={!file && !topic && false} // Optional: force inputs
                        className="w-full py-4 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl font-bold text-lg shadow-lg shadow-blue-500/25 transition-all transform hover:-translate-y-0.5 active:translate-y-0 flex items-center justify-center gap-2 group disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        <span>Generar Examen</span>
                        <Play className="w-5 h-5 fill-current opacity-80 group-hover:translate-x-1 transition-transform" />
                    </button>
                </div>
            </motion.div>
        </div>
    );
}
