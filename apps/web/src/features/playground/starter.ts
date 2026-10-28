/** A minimal spec to start typing from: one tag, one secured operation, one model. */
export const STARTER_SPEC = `openapi: 3.1.0
info:
  title: Todo API
  version: 0.1.0
  description: A tiny API to try APIForge with. Edit it and press Lint.
tags:
  - name: todos
    description: Things to do
paths:
  /todos:
    get:
      tags: [todos]
      operationId: listTodos
      summary: List todos
      responses:
        "200":
          description: Every todo
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: "#/components/schemas/Todo"
    post:
      tags: [todos]
      operationId: createTodo
      summary: Add a todo
      security:
        - bearerAuth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/TodoInput"
      responses:
        "201":
          description: Created
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Todo"
  /todos/{todoId}:
    get:
      tags: [todos]
      operationId: getTodo
      summary: Get one todo
      parameters:
        - name: todoId
          in: path
          required: true
          schema:
            type: integer
            minimum: 1
      responses:
        "200":
          description: The todo
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Todo"
        "404":
          description: No such todo
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
  schemas:
    TodoInput:
      type: object
      required: [title]
      properties:
        title:
          type: string
          minLength: 1
          maxLength: 200
        done:
          type: boolean
          default: false
    Todo:
      allOf:
        - $ref: "#/components/schemas/TodoInput"
        - type: object
          required: [id]
          properties:
            id:
              type: integer
`;
