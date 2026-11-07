package io.github.santiesc06.series76.devtools

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.navigation.toRoute
import dagger.hilt.android.lifecycle.HiltViewModel
import io.github.santiesc06.series76.data.ApiResult
import io.github.santiesc06.series76.data.AppError
import io.github.santiesc06.series76.data.ChatRepository
import io.github.santiesc06.series76.data.api.DebugInfo
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

sealed interface DebugUiState {
    data object Loading : DebugUiState
    data class Error(val error: AppError) : DebugUiState
    data class Loaded(val info: DebugInfo) : DebugUiState
}

@HiltViewModel
class DebugViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val repository: ChatRepository,
) : ViewModel() {

    private val messageId = savedStateHandle.toRoute<DebugRoute>().messageId
    private val _state = MutableStateFlow<DebugUiState>(DebugUiState.Loading)
    val state: StateFlow<DebugUiState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        _state.value = DebugUiState.Loading
        viewModelScope.launch {
            _state.value = when (val result = repository.debug(messageId)) {
                is ApiResult.Ok -> DebugUiState.Loaded(result.value)
                is ApiResult.Err -> DebugUiState.Error(result.error)
            }
        }
    }
}
