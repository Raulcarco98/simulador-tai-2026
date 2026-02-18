import { useState } from 'react';
import { motion } from 'framer-motion';
import { Play, Settings2, BookOpen, BarChart, FolderOpen, Dice5 } from 'lucide-react';
import UploadZone from './UploadZone';

export default function StartScreen({ onStart }) {
    const [numQuestions, setNumQuestions] = useState(10);
    const [minutes, setMinutes] = useState(15);
    const [file, setFile] = useState(null);
    const [topic, setTopic] = useState("");
    const [difficulty, setDifficulty] = useState("Intermedio");
    const [examMode, setExamMode] = useState('manual'); // 'manual' | 'random_1' | 'simulacro_3'
    const [folderPath, setFolderPath] = useState("");

    const handleStart = () => {
        onStart({
            numQuestions,
            minutes,
            file: examMode === 'manual' ? file : null,
            topic: examMode === 'manual' ? topic : "",
            difficulty,
            mode: examMode,
            directory_path: (examMode === 'random_1' || examMode === 'simulacro_3') ? folderPath : null
        });
    };

    const handleSelectFolder = async () => {
        if (window.electronAPI && window.electronAPI.selectDirectory) {
            const path = await window.electronAPI.selectDirectory();
            if (path) {
                setFolderPath(path);
            }
        } else {
            alert("Esta función solo está disponible en la aplicación de escritorio (Electron).");
        }
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
                        TAI Pro 2026 - v2.4 Ruleta
                    </div>
                    <h1 className="text-4xl md:text-6xl font-black text-slate-900 dark:text-white mb-6 leading-tight tracking-tight">
                        Estudia <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-indigo-600 dark:from-blue-400 dark:to-indigo-400">Cualquier Tema</span> con IA
                    </h1>
                    <p className="text-slate-600 dark:text-slate-400 text-lg mb-8 leading-relaxed max-w-lg">
                        Sube tus apuntes, escribe un tema, o deja que el azar elija por ti con el nuevo Modo Ruleta.
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

                    {/* Mode Selector (3 Options) */}
                    <div className="grid grid-cols-3 gap-2 bg-slate-100 dark:bg-slate-800/50 p-1 rounded-xl">
                        {[
                            { id: 'manual', label: 'Manual', icon: Settings2 },
                            { id: 'random_1', label: 'Ruleta', icon: Dice5 },
                            { id: 'simulacro_3', label: 'Simulacro', icon: BarChart }
                        ].map((mode) => (
                            <button
                                key={mode.id}
                                onClick={() => setExamMode(mode.id)}
                                className={`flex flex-col items-center justify-center py-2 px-1 rounded-lg text-xs font-bold transition-all gap-1.5 ${examMode === mode.id
                                    ? 'bg-white dark:bg-slate-700 shadow text-blue-600 dark:text-blue-400 ring-1 ring-black/5 dark:ring-white/10'
                                    : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-200/50 dark:hover:bg-slate-700/50'
                                    }`}
                            >
                                <mode.icon className="w-4 h-4" />
                                <span>{mode.label}</span>
                            </button>
                        ))}
                    </div>

                    {/* Source Selection Group */}
                    <div className="space-y-4">
                        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                            <BookOpen className="w-4 h-4" /> Fuente de Conocimiento
                        </h3>

                        {examMode === 'manual' ? (
                            <>
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
                            </>
                        ) : (
                            // Folder Selection View (Shared for Random & Simulacro)
                            <div className={`flex flex-col items-center justify-center p-6 border-2 border-dashed rounded-2xl text-center transition-all ${examMode === 'simulacro_3' ? 'border-indigo-500/30 bg-indigo-500/5' : 'border-emerald-500/30 bg-emerald-500/5'}`}>
                                {examMode === 'simulacro_3' ? (
                                    <BarChart className="w-12 h-12 text-indigo-500 mb-4" />
                                ) : (
                                    <Dice5 className="w-12 h-12 text-emerald-500 mb-4" />
                                )}

                                <h3 className="text-lg font-bold text-slate-800 dark:text-white mb-2">
                                    {examMode === 'simulacro_3' ? 'Simulacro Real (3 Temas)' : 'Modo Ruleta (1 Tema)'}
                                </h3>
                                <p className="text-sm text-slate-600 dark:text-slate-400 mb-6 max-w-xs mx-auto">
                                    {examMode === 'simulacro_3'
                                        ? 'Selecciona tu carpeta de apuntes. Elegiremos 3 temas al azar y haremos un muestreo inteligente.'
                                        : 'Selecciona tu carpeta. Elegiremos un archivo al azar para el examen.'}
                                </p>

                                {folderPath ? (
                                    <div className={`w-full bg-white dark:bg-slate-900 p-3 rounded-xl border mb-4 flex items-center gap-3 ${examMode === 'simulacro_3' ? 'border-indigo-500/20' : 'border-emerald-500/20'}`}>
                                        <FolderOpen className={`w-5 h-5 shrink-0 ${examMode === 'simulacro_3' ? 'text-indigo-500' : 'text-emerald-500'}`} />
                                        <span className="text-xs font-mono text-slate-600 dark:text-slate-300 break-all text-left">
                                            {folderPath}
                                        </span>
                                    </div>
                                ) : null}

                                <button
                                    onClick={handleSelectFolder}
                                    className={`px-6 py-2 text-white rounded-lg font-bold transition-all shadow-lg flex items-center gap-2 ${examMode === 'simulacro_3' ? 'bg-indigo-500 hover:bg-indigo-600 shadow-indigo-500/20' : 'bg-emerald-500 hover:bg-emerald-600 shadow-emerald-500/20'}`}
                                >
                                    <FolderOpen className="w-4 h-4" />
                                    {folderPath ? 'Cambiar Carpeta' : 'Seleccionar Carpeta'}
                                </button>
                            </div>
                        )}
                    </div>

                    {/* Exam Config Group */}
                    <div className="space-y-4">
                        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                            <BarChart className="w-4 h-4" /> Parámetros del Examen
                        </h3>

                        <div className="grid grid-cols-2 gap-4">
                            {/* Num Questions Slider */}
                            <div className="relative">
                                <label className="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-2">
                                    Preguntas: <span className="text-blue-600 dark:text-blue-400 text-sm ml-1">{numQuestions}</span>
                                </label>
                                <div className="flex items-center gap-3">
                                    <span className="text-xs text-slate-400 font-bold">5</span>
                                    <input
                                        type="range"
                                        min="5"
                                        max="10"
                                        step="1"
                                        value={numQuestions}
                                        onChange={(e) => setNumQuestions(Number(e.target.value))}
                                        className="w-full h-2 bg-slate-200 dark:bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-600 dark:accent-blue-500"
                                    />
                                    <span className="text-xs text-slate-400 font-bold">10</span>
                                </div>
                            </div>

                            {/* Difficulty */}
                            <div className="relative">
                                <label className="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-2">
                                    Dificultad
                                </label>
                                <select
                                    value={difficulty}
                                    onChange={(e) => setDifficulty(e.target.value)}
                                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-white rounded-xl px-4 py-2 appearance-none focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all font-medium text-sm"
                                >
                                    <option value="Básico">Básico</option>
                                    <option value="Intermedio">Intermedio</option>
                                    <option value="Experto">Experto</option>
                                </select>
                            </div>
                        </div>

                    </div>

                    <button
                        onClick={handleStart}
                        disabled={examMode === 'manual' ? (!file && !topic) : !folderPath}
                        className={`w-full py-4 rounded-xl font-bold text-lg shadow-lg transition-all transform hover:-translate-y-0.5 active:translate-y-0 flex items-center justify-center gap-2 group disabled:opacity-50 disabled:cursor-not-allowed text-white
                            ${examMode === 'simulacro_3'
                                ? 'bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 shadow-indigo-500/25'
                                : examMode === 'random_1'
                                    ? 'bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 shadow-emerald-500/25'
                                    : 'bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 shadow-blue-500/25'
                            }`}
                    >
                        <span>
                            {examMode === 'simulacro_3' ? 'Iniciar Simulacro Real' : examMode === 'random_1' ? '¡Girar Ruleta y Generar!' : 'Generar Examen'}
                        </span>
                        <Play className="w-5 h-5 fill-current opacity-80 group-hover:translate-x-1 transition-transform" />
                    </button>
                </div>
            </motion.div>
        </div>
    );
}
