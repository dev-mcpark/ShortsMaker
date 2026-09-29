"""UI 테마 및 스타일 정의"""

# Gradient Colors (Google AI Studio & Vertex AI Theme)
GRADIENTS = {
    'primary': 'from-violet-600 to-indigo-600',  # Vertex AI Signature
    'secondary': 'from-pink-600 to-rose-600',
    'success': 'from-emerald-500 to-teal-600',
    'warning': 'from-amber-500 to-orange-600',
    'danger': 'from-red-500 to-pink-600',
    'info': 'from-sky-500 to-blue-600',
    'purple': 'from-violet-500 to-purple-600',
    'gray': 'from-slate-700 to-slate-800',
}

# Phase Colors (for step indicators)
PHASE_COLORS = ['violet', 'purple', 'indigo', 'blue', 'teal']

# Scene Card Gradients
SCENE_GRADIENTS = [
    'from-violet-500 to-indigo-600',
    'from-fuchsia-500 to-purple-600',
    'from-blue-500 to-cyan-600',
    'from-teal-500 to-emerald-600',
    'from-amber-500 to-orange-600',
]

# Premium UI CSS Classes (Tailwind CSS via NiceGUI)
CARD_BASE = 'w-full p-0 bg-slate-900/50 border border-slate-800 rounded-lg overflow-hidden backdrop-blur-md transition-all duration-300 hover:border-violet-500/50'
CARD_HEADER = 'w-full p-4 bg-slate-900/80 border-b border-slate-800/80 flex items-center justify-between'
HEADER_TEXT = 'text-base font-semibold text-white tracking-wide'
LABEL_MUTED = 'text-xs text-slate-400 uppercase tracking-widest font-semibold'

# Google AI Studio Specific Panel Styles
SIDEBAR_LEFT = 'w-[70px] bg-slate-950 border-r border-slate-800 flex flex-col items-center py-4 justify-between shrink-0'
WORKSPACE_CENTER = 'flex-grow h-full bg-slate-900/40 overflow-hidden flex flex-col'
CONFIG_PANEL_RIGHT = 'w-[340px] bg-slate-950 border-l border-slate-800 h-full overflow-y-auto shrink-0 flex flex-col p-5'

# Status Colors
STATUS_COLORS = {
    'pending': 'text-slate-400',
    'active': 'text-violet-400',
    'complete': 'text-emerald-400',
    'error': 'text-rose-400',
}
