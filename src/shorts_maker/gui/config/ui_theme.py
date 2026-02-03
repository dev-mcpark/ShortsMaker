"""UI 테마 및 스타일 정의"""

# Gradient Colors
GRADIENTS = {
    'primary': 'from-teal-500 to-cyan-600',
    'secondary': 'from-pink-500 to-rose-600',
    'success': 'from-green-500 to-teal-600',
    'warning': 'from-amber-500 to-orange-600',
    'danger': 'from-red-500 to-pink-600',
    'info': 'from-blue-500 to-indigo-600',
    'purple': 'from-purple-500 to-indigo-600',
}

# Phase Colors (for step indicators)
PHASE_COLORS = ['pink', 'purple', 'indigo', 'blue', 'teal']

# Scene Card Gradients
SCENE_GRADIENTS = [
    'from-pink-500 to-rose-600',
    'from-purple-500 to-indigo-600',
    'from-blue-500 to-cyan-600',
    'from-teal-500 to-green-600',
    'from-amber-500 to-orange-600',
]

# Common CSS Classes
CARD_BASE = 'w-full p-0 bg-slate-800 border border-slate-700 overflow-hidden'
CARD_HEADER = 'w-full p-4'
HEADER_TEXT = 'text-lg font-bold text-white'
LABEL_MUTED = 'text-xs text-gray-400 uppercase tracking-wider'

# Status Colors
STATUS_COLORS = {
    'pending': 'text-gray-400',
    'active': 'text-teal-400',
    'complete': 'text-pink-400',
    'error': 'text-red-400',
}
