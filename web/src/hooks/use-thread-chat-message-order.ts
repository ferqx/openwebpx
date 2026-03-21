import { type ThreadChatDisplayMessage } from "@/business/thread-chat/types";

const hasOnlyEnvironmentParts = (message: ThreadChatDisplayMessage) =>
  message.parts.length > 0 &&
  message.parts.every((part) => part.type === "environment");

export const getOptimisticUserInsertIndex = (
  messages: ThreadChatDisplayMessage[],
) => {
  const lastUserIndex = [...messages]
    .map((message) => message.role)
    .lastIndexOf("user");
  if (lastUserIndex >= 0) {
    const hasMessagesAfterLastUser = messages
      .slice(lastUserIndex + 1)
      .some((message) => !hasOnlyEnvironmentParts(message));
    return hasMessagesAfterLastUser ? messages.length : lastUserIndex + 1;
  }

  const firstNonEnvironmentIndex = messages.findIndex(
    (message) => !hasOnlyEnvironmentParts(message),
  );
  if (firstNonEnvironmentIndex >= 0) {
    return firstNonEnvironmentIndex;
  }

  return messages.length;
};
