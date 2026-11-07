package io.github.santiesc06.series76.ui.conversations

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import io.github.santiesc06.series76.data.ApiResult
import io.github.santiesc06.series76.data.AppError
import io.github.santiesc06.series76.data.ChatRepository
import io.github.santiesc06.series76.data.api.SessionSummary
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

sealed interface ConversationsUiState {
    data object Loading : ConversationsUiState
    data class Error(val error: AppError) : ConversationsUiState
    data class Loaded(val sessions: List<SessionSummary>, val refreshing: Boolean = false) :
        ConversationsUiState
}

@HiltViewModel
class ConversationsViewModel @Inject constructor(
    private val repository: ChatRepository,
) : ViewModel() {

    private val _state = MutableStateFlow<ConversationsUiState>(ConversationsUiState.Loading)
    val state: StateFlow<ConversationsUiState> = _state.asStateFlow()

    /** Reloads the list; keeps the current list on screen while refreshing. */
    fun refresh() {
        _state.update { current ->
            if (current is ConversationsUiState.Loaded) current.copy(refreshing = true)
            else ConversationsUiState.Loading
        }
        viewModelScope.launch {
            _state.value = when (val result = repository.sessions()) {
                is ApiResult.Ok -> ConversationsUiState.Loaded(
                    // Newest first (US-15 AC1); conversations without messages are not shown.
                    result.value.filter { it.messageCount > 0 }.sortedByDescending { it.updatedAt },
                )
                is ApiResult.Err -> ConversationsUiState.Error(result.error)
            }
        }
    }
}
