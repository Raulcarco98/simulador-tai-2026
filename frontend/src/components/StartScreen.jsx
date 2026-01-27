import { useState } from 'react';
import { motion } from 'framer-motion';
import { Play, Settings2 } from 'lucide-react';
import UploadZone from './UploadZone';

export default function StartScreen({ onStart }) {
    const [numQuestions, setNumQuestions] = useState(10);
    const [minutes, setMinutes] = useState(15);
    const [file, setFile] = useState(null);

    const handleStart = () => {
        onStart({ numQuestions, minutes, file });
    };

    return (
        <div className="w-full max-w-4xl mx-auto flex flex-col md:flex-row gap-8 items-start">

            {/* Left Column: Intro */}
            <div className="flex-1 text-left pt-4">
                <motion.div
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.5 }}
                >
                    <div className="inline-block px-3 py-1 mb-4 text-xs font-semibold tracking-wider text-blue-600 dark:text-blue-400 uppercase bg-blue-100 dark:bg-blue-400/10 rounded-full border border-blue-200 dark:border-blue-400/20">
                        TAI Pro 2026
                    </div>
                    <h1 className="text-4xl md:text-5xl font-bold text-slate-900 dark:text-white mb-6 leading-tight">
                        Domina tu <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-indigo-600 dark:from-blue-400 dark:to-indigo-400">Oposición</span> con IA
                    </h1>
                    <p className="text-slate-600 dark:text-slate-400 text-lg mb-8 leading-relaxed">
                        Sube tus propios apuntes o practica con el temario general.
                        Generación de exámenes adaptativos en tiempo real.
                    </p>
                </motion.div>
            </div>

            {/* Right Column: Settings Card */}
            <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.2 }}
                className="w-full md:w-[450px] bg-white/70 dark:bg-[#0f172a]/80 backdrop-blur-xl border border-slate-200 dark:border-white/10 rounded-3xl p-6 shadow-2xl dark:shadow-none relative overflow-hidden"
            >
                <div className="absolute top-0 right-0 w-32 h-32 bg-indigo-500/5 dark:bg-indigo-500/10 rounded-full blur-3xl -z-10 transform translate-x-1/2 -translate-y-1/2" />

                <h2 className="text-xl font-semibold text-slate-800 dark:text-white mb-6 flex items-center gap-2">
                    <Settings2 className="w-5 h-5 text-indigo-500 dark:text-indigo-400" />
                    Configuración
                </h2>

                <div className="space-y-6">
                    {/* Upload */}
                    <div>
                        <label className="block text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
                            Material de Estudio (Opcional)
                        </label>
                        <UploadZone onFileChange={setFile} />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        {/* Num Questions */}
                        <div>
                            <label className="block text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
                                Preguntas
                            </label>
                            <div className="relative">
                                <select
                                    value={numQuestions}
                                    onChange={(e) => setNumQuestions(Number(e.target.value))}
                                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-white rounded-xl px-4 py-3 appearance-none focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all font-medium"
                                >
                                    <option value="5">5 preguntas</option>
                                    <option value="10">10 preguntas</option>
                                    <option value="20">20 preguntas</option>
                                    <option value="50">50 preguntas</option>
                                </select>
                                <div className="absolute inset-y-0 right-0 flex items-center px-2 pointer-events-none">
                                    <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path></svg>
                                </div>
                            </div>
                        </div>

                        {/* Time */}
                        <div>
                            <label className="block text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
                                Tiempo (Min)
                            </label>
                            <div className="relative">
                                <select
                                    value={minutes}
                                    onChange={(e) => setMinutes(Number(e.target.value))}
                                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-white rounded-xl px-4 py-3 appearance-none focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all font-medium"
                                >
                                    <option value="5">5 min</option>
                                    <option value="15">15 min</option>
                                    <option value="30">30 min</option>
                                    <option value="60">1 Hora</option>
                                </select>
                                <div className="absolute inset-y-0 right-0 flex items-center px-2 pointer-events-none">
                                    <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path></svg>
                                </div>
                            </div>
                        </div>
                    </div>

                    <button
                        onClick={handleStart}
                        className="w-full py-4 mt-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl font-bold text-lg shadow-lg shadow-blue-500/25 transition-all transform hover:-translate-y-0.5 active:translate-y-0 flex items-center justify-center gap-2 group"
                    >
                        <span>Generar Examen</span>
                        <Play className="w-5 h-5 fill-current opacity-80 group-hover:translate-x-1 transition-transform" />
                    </button>
                </div>
            </motion.div>
        </div>
    );
}
