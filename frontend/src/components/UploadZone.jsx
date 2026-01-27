import { useState, useCallback } from 'react';
import { UploadCloud, FileText, X } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

export default function UploadZone({ onFileChange }) {
    const [isDragging, setIsDragging] = useState(false);
    const [file, setFile] = useState(null);

    const handleDrag = useCallback((e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.type === 'dragenter' || e.type === 'dragover') {
            setIsDragging(true);
        } else if (e.type === 'dragleave') {
            setIsDragging(false);
        }
    }, []);

    const handleDrop = useCallback((e) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(false);

        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            const selectedFile = e.dataTransfer.files[0];
            handleFile(selectedFile);
        }
    }, []);

    const handleChange = (e) => {
        if (e.target.files && e.target.files[0]) {
            handleFile(e.target.files[0]);
        }
    };

    const handleFile = (selectedFile) => {
        if (selectedFile.type === "application/pdf" || selectedFile.type === "text/plain" || selectedFile.name.endsWith(".md")) {
            setFile(selectedFile);
            onFileChange(selectedFile);
        } else {
            alert("Solo se permiten archivos PDF, TXT o MD.");
        }
    };

    const removeFile = (e) => {
        e.stopPropagation();
        setFile(null);
        onFileChange(null);
    };

    return (
        <div className="w-full">
            <AnimatePresence mode="wait">
                {!file ? (
                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, scale: 0.95 }}
                        key="dropzone"
                    >
                        <label
                            className={`relative flex flex-col items-center justify-center w-full h-40 rounded-2xl border-2 border-dashed transition-all cursor-pointer overflow-hidden group
                ${isDragging
                                    ? "border-blue-500 bg-blue-500/10"
                                    : "border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50 hover:bg-slate-100 dark:hover:bg-slate-800/50 hover:border-slate-400 dark:hover:border-slate-500"
                                }`}
                            onDragEnter={handleDrag}
                            onDragLeave={handleDrag}
                            onDragOver={handleDrag}
                            onDrop={handleDrop}
                        >
                            <div className="flex flex-col items-center justify-center pt-5 pb-6 text-center px-4">
                                <UploadCloud className={`w-10 h-10 mb-3 transition-colors ${isDragging ? "text-blue-500" : "text-slate-400 dark:text-slate-500 group-hover:text-slate-600 dark:group-hover:text-slate-400"}`} />
                                <p className="mb-2 text-sm text-slate-600 dark:text-slate-400">
                                    <span className="font-semibold text-slate-800 dark:text-slate-300">Haz clic o arrastra</span> tu temario aquí
                                </p>
                                <p className="text-xs text-slate-500">PDF, TXT o Markdown (Max 10MB)</p>
                            </div>
                            <input type="file" className="hidden" onChange={handleChange} accept=".pdf,.txt,.md" />
                        </label>
                    </motion.div>
                ) : (
                    <motion.div
                        initial={{ opacity: 0, scale: 0.95 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0, y: 10 }}
                        key="file-preview"
                        className="w-full h-40 rounded-2xl border border-blue-500/30 bg-blue-500/5 flex flex-col items-center justify-center relative p-4 group"
                    >
                        <div className="absolute top-2 right-2">
                            <button onClick={removeFile} className="p-1 rounded-full hover:bg-slate-200 dark:hover:bg-white/10 text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-white transition-colors">
                                <X className="w-5 h-5" />
                            </button>
                        </div>

                        <FileText className="w-12 h-12 text-blue-500 dark:text-blue-400 mb-3" />
                        <p className="text-sm font-medium text-slate-800 dark:text-slate-200 truncate max-w-full px-4">{file.name}</p>
                        <p className="text-xs text-blue-600/70 dark:text-blue-300/70 mt-1">Archivo cargado correctamente</p>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}
