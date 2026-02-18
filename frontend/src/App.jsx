import { useState, useRef, useEffect } from "react";
import Timer from "./components/Timer";
import QuestionCard from "./components/QuestionCard";
import Dashboard from "./components/Dashboard";
import StartScreen from "./components/StartScreen";
import ThemeToggle from "./components/ThemeToggle";
import { BrainCircuit, Terminal } from "lucide-react";

const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

function App() {
  const [gameState, setGameState] = useState("start"); // start, generating, playing, finished
  const [questions, setQuestions] = useState([]);
  const [answers, setAnswers] = useState([]);
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [config, setConfig] = useState(null);
  const [streamProgress, setStreamProgress] = useState(0);
  const [debugInfo, setDebugInfo] = useState(null);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [terminalLogs, setTerminalLogs] = useState([]);
  const [lastContext, setLastContext] = useState(null);
  const terminalEndRef = useRef(null);

  // Load lastContext from localStorage
  useEffect(() => {
    const savedContext = localStorage.getItem("lastContext");
    if (savedContext) {
      setLastContext(savedContext);
    }
  }, []);

  // Auto-scroll terminal to bottom
  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [terminalLogs]);

  const addLog = (msg) => {
    const timestamp = new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    setTerminalLogs(prev => [...prev, `[${timestamp}] ${msg}`]);
  };

  // Generate Exam (SSE Streaming)
  const handleStartExam = async (settings) => {
    setConfig(settings);
    setLoading(true);
    setGameState("generating");
    setStreamProgress(0);
    setDebugInfo(null);
    setTerminalLogs([]);
    addLog("Conectando con el servidor...");

    const formData = new FormData();
    formData.append("num_questions", settings.numQuestions);
    formData.append("difficulty", settings.difficulty || "Intermedio");

    if (settings.topic) {
      formData.append("topic", settings.topic);
    }
    if (settings.mode === 'random' && settings.directory_path) {
      formData.append("directory_path", settings.directory_path);
      addLog(`[RULETA] Modo aleatorio activado en: ${settings.directory_path}`);
    } else if (settings.file) {
      formData.append("file", settings.file);
    } else if (settings.context || lastContext) {
      // Use existing context if available and no new file
      formData.append("context", settings.context || lastContext);
      addLog("Usando contexto previo de memoria...");
    }

    try {
      const res = await fetch(`${API_URL}/generate-exam`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Error del servidor (${res.status})`);
      }

      // === SSE STREAM READER ===
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let allQuestions = [];
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE lines (format: "data: <json>\n\n")
        const parts = buffer.split("\n\n");
        buffer = parts.pop(); // Keep incomplete part in buffer

        for (const part of parts) {
          const trimmed = part.trim();
          if (trimmed.startsWith("data: ")) {
            const payload = trimmed.slice(6);
            if (payload === "[DONE]") {
              addLog("Stream finalizado.");
              continue;
            }
            try {
              const parsed = JSON.parse(payload);

              // Log event from backend
              if (parsed && parsed.type === "log") {
                addLog(parsed.msg);
                continue;
              }

              // Context update event
              if (parsed && parsed.type === "context") {
                const newContext = parsed.content;
                if (newContext) {
                  setLastContext(newContext);
                  localStorage.setItem("lastContext", newContext);
                  addLog("Contexto actualizado y guardado.");
                }
                continue;
              }

              // Question batch
              if (!Array.isArray(parsed)) {
                addLog(`[WARN] Respuesta no es array: ${payload.slice(0, 200)}`);
                setDebugInfo(prev => (prev || "") + "\n[NOT ARRAY] " + payload.slice(0, 500));
                continue;
              }
              allQuestions = [...allQuestions, ...parsed];
              setStreamProgress(allQuestions.length);
            } catch (e) {
              addLog(`[ERROR] Parse JSON falló: ${payload.slice(0, 100)}`);
              setDebugInfo(prev => (prev || "") + "\n[PARSE ERROR] " + payload.slice(0, 500));
            }
          }
        }
      }

      if (allQuestions.length > 0) {
        setQuestions(allQuestions);
        setAnswers(allQuestions.map(q => ({
          questionId: q.id,
          selectedOption: null,
          isCorrect: false,
          answered: false
        })));
        setCurrentQuestionIndex(0);
        setGameState("playing");
      } else {
        setDebugInfo(prev => prev || "El servidor no devolvió preguntas. Revisa la API Key o intenta de nuevo.");
        setGameState("start");
      }
    } catch (error) {
      console.error("Failed to generate exam:", error);
      addLog(`❌ Error fatal: ${error.message || "Error de conexión"}`);
      setDebugInfo(prev => (prev || "") + "\n[ERROR] " + (error.message || "Error de conexión"));
      setGameState("start");
    } finally {
      setLoading(false);
      setStreamProgress(0);
    }
  };

  const handleOptionSelect = (optionIndex) => {
    const currentQuestion = questions[currentQuestionIndex];
    if (!currentQuestion) return;

    setAnswers(prev => {
      const newAnswers = [...prev];
      newAnswers[currentQuestionIndex] = {
        questionId: currentQuestion.id,
        selectedOption: optionIndex,
        isCorrect: optionIndex === currentQuestion.correct_index,
        answered: true
      };
      return newAnswers;
    });
  };

  const handleNext = () => {
    if (currentQuestionIndex < questions.length - 1) {
      setCurrentQuestionIndex(prev => prev + 1);
    }
  };

  const handlePrev = () => {
    if (currentQuestionIndex > 0) {
      setCurrentQuestionIndex(prev => prev - 1);
    }
  };

  const handleFinish = () => {
    setGameState("finished");
  };

  const handleTimeUp = () => {
    setGameState("finished");
  };

  const handleRestart = () => {
    setGameState("start");
    setQuestions([]);
    setAnswers([]);
    setCurrentQuestionIndex(0);
  };

  const handleRetry = () => {
    if (config) {
      handleStartExam(config);
    } else {
      setGameState("start");
    }
  };

  const currentQuestion = questions[currentQuestionIndex];
  const currentAnswer = answers[currentQuestionIndex];

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-[#020617] text-slate-900 dark:text-slate-100 font-sans selection:bg-blue-500/30 overflow-x-hidden transition-colors duration-300">
      {/* Background Decor */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-blue-600/10 rounded-full blur-[100px]" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-indigo-600/10 rounded-full blur-[100px]" />
      </div>

      <div className="relative max-w-6xl mx-auto px-6 py-6 min-h-screen flex flex-col">
        {/* Header */}
        <header className="flex items-center justify-between mb-8 z-10 w-full">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-500/10 rounded-lg border border-blue-500/20">
              <BrainCircuit className="w-8 h-8 text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <h1 className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-600 to-indigo-600 dark:from-blue-200 dark:to-indigo-200 hidden md:block">
                Simulador TAI 2026
              </h1>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {gameState === "playing" && (
              <>
                <div className="text-sm font-medium text-slate-600 dark:text-slate-400 bg-white/50 dark:bg-slate-900/50 px-4 py-2 rounded-full border border-slate-200 dark:border-white/5 shadow-sm dark:shadow-none">
                  Pregunta <span className="text-slate-900 dark:text-white font-bold">{currentQuestionIndex + 1}</span> / {questions.length}
                </div>
                <Timer
                  duration={config?.minutes * 60 || 900}
                  onTimeUp={handleTimeUp}
                  active={gameState === "playing"}
                />
              </>
            )}
            <button
              onClick={() => setTerminalOpen(prev => !prev)}
              className={`relative p-2 rounded-lg border transition-all duration-200 ${terminalOpen
                ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-600 dark:text-emerald-400'
                : 'bg-white/50 dark:bg-slate-800/50 border-slate-200 dark:border-white/10 text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-white'
                }`}
              title="Terminal de logs"
            >
              <Terminal className="w-5 h-5" />
              {terminalLogs.length > 0 && (
                <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-emerald-500 rounded-full animate-pulse" />
              )}
            </button>
            <ThemeToggle />
          </div>
        </header>

        {/* Main Content */}
        <main className="flex-1 flex flex-col items-center justify-center relative z-10">

          {gameState === "start" && (
            <StartScreen onStart={handleStartExam} />
          )}

          {gameState === "generating" && (
            <div className="flex flex-col items-center justify-center text-center">
              <div className="w-16 h-16 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-6"></div>
              <h2 className="text-2xl font-bold text-slate-800 dark:text-white mb-2">Generando Examen con IA...</h2>
              <p className="text-slate-600 dark:text-slate-400 max-w-md">
                {streamProgress > 0
                  ? `${streamProgress} / ${config?.numQuestions || '?'} preguntas generadas...`
                  : "Conectando con Gemini. Esto puede tardar unos segundos."
                }
              </p>
              {streamProgress > 0 && (
                <div className="w-64 h-2 bg-slate-200 dark:bg-slate-700 rounded-full mt-4 overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-blue-500 to-indigo-500 rounded-full transition-all duration-500"
                    style={{ width: `${(streamProgress / (config?.numQuestions || 10)) * 100}%` }}
                  />
                </div>
              )}
            </div>
          )}

          {/* Debug Panel - shows raw server response on error */}
          {debugInfo && gameState === "start" && (
            <div className="w-full max-w-2xl mt-6 p-4 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/40 rounded-xl">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-bold text-red-700 dark:text-red-300 uppercase tracking-wider">🐛 Debug: Error de generación</h3>
                <button
                  onClick={() => setDebugInfo(null)}
                  className="text-xs text-red-500 hover:text-red-700 dark:hover:text-red-300 transition-colors"
                >
                  Cerrar
                </button>
              </div>
              <pre className="text-xs text-red-800 dark:text-red-200 bg-red-100 dark:bg-red-900/40 p-3 rounded-lg overflow-x-auto max-h-48 whitespace-pre-wrap break-all">{debugInfo}</pre>
            </div>
          )}

          {gameState === "playing" && currentQuestion && (
            <QuestionCard
              question={currentQuestion}
              selectedOption={currentAnswer?.selectedOption ?? null}
              showResult={currentAnswer?.answered ?? false}
              correctOption={currentQuestion.correct_index}
              onOptionSelect={handleOptionSelect}
              onNext={handleNext}
              onPrev={handlePrev}
              isFirst={currentQuestionIndex === 0}
              isLast={currentQuestionIndex === questions.length - 1}
              onFinish={handleFinish}
            />
          )}

          {gameState === "finished" && (
            <Dashboard
              answers={answers}
              questions={questions}
              onRestart={handleRestart}
              onRetry={(newDifficulty) => {
                if (config) {
                  handleStartExam({ ...config, difficulty: newDifficulty || config.difficulty });
                } else {
                  setGameState("start");
                }
              }}
            />
          )}
        </main>

        {/* Terminal Panel */}
        {terminalOpen && (
          <div className="fixed bottom-0 left-0 right-0 z-50 border-t border-emerald-500/30 bg-[#0d1117] shadow-2xl transition-all duration-300" style={{ height: '280px' }}>
            <div className="flex items-center justify-between px-4 py-2 bg-[#161b22] border-b border-white/10">
              <div className="flex items-center gap-2">
                <div className="flex gap-1.5">
                  <div className="w-3 h-3 rounded-full bg-red-500" />
                  <div className="w-3 h-3 rounded-full bg-yellow-500" />
                  <div className="w-3 h-3 rounded-full bg-green-500" />
                </div>
                <span className="text-xs text-slate-400 font-mono ml-2">Terminal — Simulador TAI</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500">{terminalLogs.length} líneas</span>
                <button
                  onClick={() => setTerminalLogs([])}
                  className="text-xs text-slate-500 hover:text-white transition-colors px-2 py-0.5 rounded border border-white/10"
                >
                  Limpiar
                </button>
                <button
                  onClick={() => setTerminalOpen(false)}
                  className="text-xs text-slate-500 hover:text-white transition-colors px-2 py-0.5 rounded border border-white/10"
                >
                  Cerrar
                </button>
              </div>
            </div>
            <div className="overflow-y-auto p-4 font-mono text-xs leading-relaxed" style={{ height: 'calc(100% - 40px)' }}>
              {terminalLogs.length === 0 ? (
                <p className="text-slate-500 italic">Esperando logs... Genera un examen para ver la actividad.</p>
              ) : (
                terminalLogs.map((log, i) => (
                  <div key={i} className={`${log.includes('❌') ? 'text-red-400' :
                    log.includes('⚠️') || log.includes('[WARN]') ? 'text-yellow-400' :
                      log.includes('✅') ? 'text-emerald-400' :
                        log.includes('🚀') || log.includes('🏁') ? 'text-blue-400' :
                          'text-slate-300'
                    }`}>{log}</div>
                ))
              )}
              <div ref={terminalEndRef} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
