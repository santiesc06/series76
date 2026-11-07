package io.github.santiesc06.series76.ui.chat

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.navigation.toRoute
import dagger.hilt.android.lifecycle.HiltViewModel
import io.github.santiesc06.series76.data.ApiResult
import io.github.santiesc06.series76.data.AppError
import io.github.santiesc06.series76.data.ChatRepository
import io.github.santiesc06.series76.data.api.ConversationResponse
import io.github.santiesc06.series76.data.api.HistoryMessage
import io.github.santiesc06.series76.data.api.Product
import io.github.santiesc06.series76.data.api.QuickReply
import io.github.santiesc06.series76.navigation.ChatRoute
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.UUID
import javax.inject.Inject

const val MAX_QUERY_LENGTH = 2000 // the backend rejects longer queries (ConversationRequest)

sealed interface ChatItem {
    val id: String

    data class User(override val id: String, val text: String, val failed: Boolean = false) :
        ChatItem

    data class Assistant(
        override val id: String, // the backend message id, used by the debug screen
        val text: String,
        val status: String,
        val view: String,
        val products: List<Product>,
        val alternatives: List<Product>,
        val quickReplies: List<QuickReply>,
    ) : ChatItem
}

data class ChatUiState(
    val sessionId: String? = null,
    val title: String? = null,
    val items: List<ChatItem> = emptyList(),
    val loadingHistory: Boolean = false,
    val historyError: AppError? = null,
    val sending: Boolean = false,
    val sendError: AppError? = null,
)

@HiltViewModel
class ChatViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val repository: ChatRepository,
) : ViewModel() {

    private val route = savedStateHandle.toRoute<ChatRoute>()
    private val _state = MutableStateFlow(ChatUiState(sessionId = route.sessionId))
    val state: StateFlow<ChatUiState> = _state.asStateFlow()

    init {
        if (route.sessionId != null) loadHistory()
    }

    /** Opens a saved conversation with its product cards (US-16 AC1, design C7 snapshots). */
    fun loadHistory() {
        val sessionId = _state.value.sessionId ?: return
        _state.update { it.copy(loadingHistory = true, historyError = null) }
        viewModelScope.launch {
            when (val result = repository.history(sessionId)) {
                is ApiResult.Ok -> _state.update {
                    it.copy(
                        loadingHistory = false,
                        title = result.value.title,
                        items = result.value.messages.map(::toItem),
                    )
                }
                is ApiResult.Err -> _state.update {
                    it.copy(loadingHistory = false, historyError = result.error)
                }
            }
        }
    }

    fun send(text: String) {
        val query = text.trim().take(MAX_QUERY_LENGTH)
        if (query.isEmpty() || _state.value.sending) return
        val pending = ChatItem.User(id = "local-${UUID.randomUUID()}", text = query)
        _state.update {
            it.copy(items = it.items + pending, sending = true, sendError = null)
        }
        submit(pending)
    }

    /** Re-sends a failed question. The backend saved nothing for it (design B8). */
    fun retry(item: ChatItem.User) {
        if (_state.value.sending) return
        _state.update { state ->
            state.copy(
                items = state.items.map { if (it.id == item.id) item.copy(failed = false) else it },
                sending = true,
                sendError = null,
            )
        }
        submit(item.copy(failed = false))
    }

    private fun submit(item: ChatItem.User) {
        viewModelScope.launch {
            when (val result = repository.send(_state.value.sessionId, item.text)) {
                is ApiResult.Ok -> _state.update {
                    it.copy(
                        sessionId = result.value.sessionId,
                        title = it.title ?: item.text.take(60),
                        items = it.items + toItem(result.value),
                        sending = false,
                    )
                }
                is ApiResult.Err -> _state.update { state ->
                    state.copy(
                        items = state.items.map {
                            if (it.id == item.id) item.copy(failed = true) else it
                        },
                        sending = false,
                        sendError = result.error,
                    )
                }
            }
        }
    }

    private fun toItem(r: ConversationResponse) = ChatItem.Assistant(
        id = r.messageId,
        text = r.answer,
        status = r.status,
        view = r.view,
        products = r.products,
        alternatives = r.alternatives,
        quickReplies = r.quickReplies,
    )

    private fun toItem(m: HistoryMessage): ChatItem = if (m.role == "user") {
        ChatItem.User(id = m.id, text = m.content)
    } else {
        ChatItem.Assistant(
            id = m.id,
            text = m.content,
            status = m.status ?: "answered",
            view = m.view ?: "none",
            products = m.products,
            alternatives = m.alternatives,
            quickReplies = m.quickReplies,
        )
    }
}
