import { useState } from "react";
import Timer from "./components/Timer";
import QuestionCard from "./components/QuestionCard";
import Dashboard from "./components/Dashboard";
import StartScreen from "./components/StartScreen";
import ThemeToggle from "./components/ThemeToggle";
import { BrainCircuit } from "lucide-react";

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

  // Generate Exam (SSE Streaming)
  const handleStartExam = async (settings) => {
    setConfig(settings);
    setLoading(true);
    setGameState("generating");
    setStreamProgress(0);
    setDebugInfo(null);

    const formData = new FormData();
    formData.append("num_questions", settings.numQuestions);
    formData.append("difficulty", settings.difficulty || "Intermedio");

    if (settings.topic) {
      formData.append("topic", settings.topic);
    }
    if (settings.file) {
      formData.append("file", settings.file);
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
            if (payload === "[DONE]") continue;
            try {
              const batch = JSON.parse(payload);
              if (!Array.isArray(batch)) {
                console.warn("SSE batch is not an array:", payload.slice(0, 200));
                setDebugInfo(prev => (prev || "") + "\n[NOT ARRAY] " + payload.slice(0, 500));
                continue;
              }
              allQuestions = [...allQuestions, ...batch];
              setStreamProgress(allQuestions.length);
            } catch (e) {
              console.warn("SSE parse error:", e);
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
              onRetry={handleRetry}
            />
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
